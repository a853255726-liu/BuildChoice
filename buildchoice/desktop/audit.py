"""On-demand evidence ledger. Python stdlib only; no LLM or classifier calls.

The collector reads bytes itself. Caller assertions never become read receipts.
Exact JSON pointers can support literal values; prose remains interpretation-pending.
This is an aid to review, not a general semantic or authorization verifier.
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

MAX_BYTES = 256 * 1024
PRIVATE_PARTS = {'.git', '.codex', '.agents', '.aws', '.ssh', '.buildchoice_audit', '.gate_audit', '.venv', 'node_modules'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def pointer_value(text, pointer):
    value = json.loads(text)
    if pointer == '':
        return value
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValueError('JSON pointer must start with /')
    for part in pointer[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            if not part.isdigit() or (len(part) > 1 and part.startswith('0')):
                raise ValueError('Invalid array index')
            value = value[int(part)]
        else:
            value = value[part]
    return value


class Ledger:
    def __init__(self, workspace, database=None):
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError('Workspace must be a directory')
        self.database = Path(database) if database else self.workspace / '.buildchoice_audit' / 'ledger.sqlite3'
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, workspace TEXT, title TEXT,
              task TEXT, created TEXT, provenance TEXT);
            CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, session TEXT, locator TEXT,
              content TEXT, digest TEXT, created TEXT, origin TEXT, metadata TEXT);
            CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, session TEXT, data TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, session TEXT, decision TEXT,
              disposition TEXT, note TEXT, created TEXT, fingerprint TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, session TEXT,
              kind TEXT, data TEXT, created TEXT);
            ''')

    def connect(self):
        db = sqlite3.connect(self.database, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def event(self, db, session, kind, data):
        db.execute('INSERT INTO events(session,kind,data,created) VALUES(?,?,?,?)',
                   (session, kind, encode(data), now()))

    def session(self, session):
        with self.connect() as db:
            row = db.execute('SELECT * FROM sessions WHERE id=?', (session,)).fetchone()
        if row is None or row['workspace'] != str(self.workspace):
            raise ValueError('Unknown session in this workspace')
        return dict(row)

    def start(self, title, task, provenance='live'):
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError('Title is required (max 200 characters)')
        if not isinstance(task, str) or len(task) > MAX_BYTES:
            raise ValueError('Invalid task declaration')
        session = 'audit-' + uuid.uuid4().hex[:16]
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',
                       (session, str(self.workspace), title, task, now(), provenance))
            self.event(db, session, 'SESSION_STARTED', {'title': title, 'task_origin': 'caller_declared'})
        return self.session(session)

    def list_sessions(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM sessions WHERE workspace=? ORDER BY created DESC',
                                               (str(self.workspace),))]

    def path(self, relative):
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ':' in relative:
            raise ValueError('Use a workspace-relative file path')
        parts = Path(relative.replace('\\', '/')).parts
        if '..' in parts or any(p.lower() in PRIVATE_PARTS or p.lower().startswith('.env') for p in parts):
            raise ValueError('Private or escaping path is excluded')
        current = self.workspace
        for part in parts:
            current = current / part
            if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
                raise ValueError('Linked evidence paths are excluded')
        path = current.resolve(strict=True)
        if not path.is_relative_to(self.workspace) or not path.is_file():
            raise ValueError('Evidence must be a workspace file')
        return path

    def read(self, session, relative):
        self.session(session)
        path = self.path(relative)
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('Evidence exceeds 256 KiB; select a smaller source')
        content = raw.decode('utf-8-sig')
        source = {'id': 'src-' + uuid.uuid4().hex[:16], 'session': session,
                  'locator': path.relative_to(self.workspace).as_posix(), 'content': content,
                  'digest': sha(raw), 'created': now(), 'origin': 'collector_file_read',
                  'metadata': encode({'bytes': len(raw), 'encoding': 'utf-8',
                                      'meaning': 'read by audit collector; not proof of original Agent reading'})}
        with self.connect() as db:
            db.execute('INSERT INTO sources VALUES(:id,:session,:locator,:content,:digest,:created,:origin,:metadata)', source)
            self.event(db, session, 'SOURCE_READ', {k: source[k] for k in ('id', 'locator', 'digest')})
        return source

    def decide(self, session, title, value, refs=None, impact='关键交付', rationale=''):
        self.session(session)
        refs = refs or []
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or not isinstance(refs, list) or len(refs) > 20:
            raise ValueError('Invalid decision title or references')
        if len(encode(value)) > 10000 or len(rationale) > 10000:
            raise ValueError('Decision is too large')
        with self.connect() as db:
            for ref in refs:
                if not isinstance(ref, dict) or set(ref) - {'source_id', 'pointer', 'quote'} or 'source_id' not in ref:
                    raise ValueError('Reference: source_id and exactly one pointer/quote')
                if ('pointer' in ref) == ('quote' in ref):
                    raise ValueError('Reference needs exactly one pointer or quote')
                if not db.execute('SELECT 1 FROM sources WHERE id=? AND session=?', (ref['source_id'], session)).fetchone():
                    raise ValueError('Reference must belong to this session')
                if 'pointer' in ref and not isinstance(ref['pointer'], str):
                    raise ValueError('Pointer must be a string')
                if 'quote' in ref and (not isinstance(ref['quote'], str) or not ref['quote'].strip()):
                    raise ValueError('Quote must be nonempty')
            decision = {'id': 'dec-' + uuid.uuid4().hex[:16], 'title': title, 'value': value,
                        'refs': refs, 'impact': impact, 'rationale': rationale}
            db.execute('INSERT INTO decisions VALUES(?,?,?,?)', (decision['id'], session, encode(decision), now()))
            self.event(db, session, 'DECISION_DECLARED', decision)
        return decision

    def report(self, session):
        result = self.session(session)
        with self.connect() as db:
            sources = {r['id']: dict(r) for r in db.execute('SELECT * FROM sources WHERE session=? ORDER BY created', (session,))}
            decisions = [json.loads(r['data']) for r in db.execute('SELECT data FROM decisions WHERE session=? ORDER BY created', (session,))]
            reviews = [dict(r) for r in db.execute('SELECT * FROM reviews WHERE session=? ORDER BY created', (session,))]
            events = [dict(r) for r in db.execute('SELECT * FROM events WHERE session=? ORDER BY id', (session,))]
        for source in sources.values():
            try:
                path = self.path(source['locator'])
                with path.open('rb') as stream:
                    raw = stream.read(MAX_BYTES + 1)
                source['current'] = len(raw) <= MAX_BYTES and sha(raw) == source['digest']
            except (OSError, ValueError):
                source['current'] = False
        for decision in decisions:
            findings, bindings, values = [], [], []
            if not decision['refs']:
                findings.append('NO_EVIDENCE')
            for ref in decision['refs']:
                source = sources[ref['source_id']]
                binding = {'source_id': source['id'], 'locator': source['locator'], 'sha256': source['digest'],
                           'current': source['current'], 'kind': 'json_pointer' if 'pointer' in ref else 'text_quote'}
                if not source['current']:
                    findings.append('SOURCE_CHANGED')
                try:
                    if 'pointer' in ref:
                        actual = pointer_value(source['content'], ref['pointer'])
                        binding.update({'pointer': ref['pointer'], 'observed': actual, 'bound': True})
                        values.append(encode(actual))
                        if encode(actual) != encode(decision['value']):
                            findings.append('VALUE_MISMATCH')
                    else:
                        binding.update({'quote': ref['quote'], 'bound': ref['quote'] in source['content']})
                        findings.append('INTERPRETATION_PENDING' if binding['bound'] else 'QUOTE_NOT_FOUND')
                except (ValueError, KeyError, TypeError, IndexError):
                    binding['bound'] = False
                    findings.append('POINTER_NOT_FOUND')
                bindings.append(binding)
            if len(set(values)) > 1:
                findings.append('CONFLICTING_VALUES')
            fingerprint = sha(encode({'decision': decision, 'bindings': bindings, 'findings': sorted(set(findings))}).encode())
            review = next((r for r in reversed(reviews) if r['decision'] == decision['id'] and r['fingerprint'] == fingerprint), None)
            decision.update({'findings': sorted(set(findings)), 'bindings': bindings, 'fingerprint': fingerprint,
                             'review': review, 'status': 'reviewed' if review else 'attention' if findings else 'linked'})
        result.update({'schema_version': 'audit.v1', 'sources': list(sources.values()), 'decisions': decisions,
                       'reviews': reviews, 'events': events,
                       'summary': {'decisions': len(decisions), 'attention': sum(d['status'] == 'attention' for d in decisions),
                                   'linked': sum(d['status'] == 'linked' for d in decisions),
                                   'reviewed': sum(d['status'] == 'reviewed' for d in decisions)},
                       'scope': '显式登记的关键决策；结构化字面核验与证据定位，未登记决策不计入覆盖率'})
        return result

    def review(self, session, decision_id, disposition, note):
        if disposition not in ('accept', 'revise', 'ask') or not isinstance(note, str) or not note.strip() or len(note) > 4000:
            raise ValueError('Review needs accept/revise/ask and a concrete note')
        decision = next((d for d in self.report(session)['decisions'] if d['id'] == decision_id), None)
        if decision is None:
            raise ValueError('Unknown decision')
        with self.connect() as db:
            db.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)',
                       ('rev-' + uuid.uuid4().hex[:16], session, decision_id, disposition, note, now(), decision['fingerprint']))
            self.event(db, session, 'REVIEW_RECORDED', {'decision': decision_id, 'disposition': disposition, 'note': note})
        return self.report(session)


FINDING_LABELS = {'NO_EVIDENCE': '未绑定证据', 'SOURCE_CHANGED': '证据文件已变化或不可读',
                  'VALUE_MISMATCH': '登记取值与来源字面值不一致', 'INTERPRETATION_PENDING': '原文已定位，语义解释待复核',
                  'QUOTE_NOT_FOUND': '引用原文不存在', 'POINTER_NOT_FOUND': 'JSON 路径不存在',
                  'CONFLICTING_VALUES': '所引来源字面取值冲突'}


def markdown(report):
    lines = ['# ' + report['title'], '', '> BuildChoice · 按需决策审计', '',
             '任务：' + report['task'], '', '来源类型：' + report['provenance'], '',
             '登记决定 {} · 待复核 {} · 字面匹配 {} · 已记录复核 {}'.format(*[report['summary'][k] for k in ('decisions', 'attention', 'linked', 'reviewed')]), '',
             '字面匹配表示已绑定实际读取的结构化值；业务适用性由复核者判断。', '']
    for d in report['decisions']:
        lines += ['## ' + d['title'], '', '登记取值：`' + encode(d['value']) + '`', '',
                  '状态：' + d['status'], '', '依据说明：' + d['rationale'], '']
        for f in d['findings']:
            lines += ['- ' + FINDING_LABELS[f]]
        for b in d['bindings']:
            lines += ['- 来源：`' + b['locator'] + '` · SHA256 `' + b['sha256'] + '`',
                      '  定位：' + encode({k: b[k] for k in ('pointer', 'quote', 'observed', 'bound', 'current') if k in b})]
        if d['review']:
            lines += ['', '复核记录：' + d['review']['disposition'] + ' — ' + d['review']['note']]
        lines += ['']
    lines += ['## 来源与范围', '', report['scope'], '',
              '文件由本次审计读取并保存快照。读取回执不证明原 Agent 曾读取，也不自动证明文件具有授权效力。', '',
              '审计ID：`' + report['id'] + '`；事件数：' + str(len(report['events'])), '']
    return '\n'.join(lines)
