"""Bounded local text snapshots of the actual workspace, independent of Git HEAD."""
import difflib
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid
from .audit import linked_path, PRIVATE_PARTS
from .decision_store import fingerprint
from .product_contracts import validate
from . import product_store as ps

FILE_LIMIT = 256 * 1024
SNAPSHOT_LIMIT = 8 * 1024 * 1024
PROJECT_LIMIT = 64 * 1024 * 1024
RETENTION_SECONDS = 30 * 86400
FILE_COUNT_LIMIT = 10000
PRIVATE = PRIVATE_PARTS | {'private', 'secrets', 'credentials', 'userdata', 'user_data',
    'personal', 'data', 'datasets', 'backups', 'venv', '.cache', '__pycache__', 'dist', 'build'}
SECRET_NAMES = {'id_rsa', 'id_ed25519', 'credentials.json', 'credentials', '.npmrc', '.pypirc',
    'authorized_keys', 'known_hosts', 'binding.json', 'settings.local.json', 'config.local.json'}
SECRET_SUFFIX = {'.key', '.pem', '.p12', '.pfx', '.token', '.sqlite', '.sqlite3', '.db'}
SECRET_CONTENT = re.compile(r'''(?ix)(?:api[_-]?key|access[_-]?token|secret|password|private[_-]?key)["']?\s*[:=]\s*["'][^"'\r\n]{12,}["']|-----BEGIN\s+(?:\w+\s+)?PRIVATE KEY-----''')


def safe_root(store):
    base = Path(os.environ.get('BUILDCHOICE_DATA', str(Path.home() / '.buildchoice'))).absolute()
    root = base / 'product-snapshots' / fingerprint(str(store.workspace))[:24]
    for path in [root, *root.parents]:
        if linked_path(path): raise ValueError('Linked snapshot storage is excluded')
    root = root.resolve()
    if root.is_relative_to(store.workspace): raise ValueError('Snapshot storage must be outside the code workspace')
    if os.name == 'nt' and not str(root).startswith('\\\\?\\'):
        root = Path('\\\\?\\' + str(root))
    root.mkdir(parents=True, exist_ok=True)
    return root


def normalize(relative):
    if not isinstance(relative, str) or not relative or len(relative) > 512 or ':' in relative or '\x00' in relative:
        raise ValueError('Unsupported snapshot path')
    path = Path(relative.replace('\\', '/'))
    if path.anchor or path.is_absolute() or '..' in path.parts or any(p.endswith((' ', '.')) for p in path.parts):
        raise ValueError('Snapshot scope must stay in workspace')
    return path.as_posix()


def excluded(path, excluded_paths=()):
    parts = Path(path).parts
    if any(p.lower() in PRIVATE or p.lower().startswith('.env') for p in parts): return 'private_directory_or_environment'
    if parts and (parts[-1].lower() in SECRET_NAMES or Path(parts[-1]).suffix.lower() in SECRET_SUFFIX): return 'sensitive_file'
    if any(path == p or path.startswith(p.rstrip('/') + '/') for p in excluded_paths): return 'explicit_exclusion'
    if parts and parts[-1].startswith('BUILDCHOICE_PRODUCT_'): return 'generated_product_document'
    return None


def workspace_path(store, relative):
    relative = normalize(relative)
    current = store.workspace
    for part in Path(relative).parts:
        current /= part
        if linked_path(current): raise ValueError('linked_path')
    if not current.resolve().is_relative_to(store.workspace): raise ValueError('escaping_path')
    return current


def enumerate_paths(store, scopes, excluded_paths):
    found = {}; visited = 0
    for scope in scopes:
        scope = normalize(scope)
        reason = excluded(scope, excluded_paths)
        if reason: found[scope] = reason; continue
        try: path = workspace_path(store, scope)
        except (OSError, ValueError): found[scope] = 'linked_or_unreadable_path'; continue
        if not path.exists(): found[scope] = 'absent_at_capture'; continue
        pending = [path]
        while pending:
            current = pending.pop(); visited += 1
            if visited > FILE_COUNT_LIMIT: raise ValueError('Snapshot traversal exceeds file/directory limit; narrow scope')
            relative = current.relative_to(store.workspace).as_posix()
            reason = excluded(relative, excluded_paths)
            if reason: found[relative] = reason; continue
            if linked_path(current): found[relative] = 'linked_path'; continue
            try:
                if current.is_dir(): pending.extend(sorted(current.iterdir(), reverse=True))
                elif current.is_file(): found[relative] = None
                else: found[relative] = 'unsupported_file_type'
            except OSError: found[relative] = 'unreadable_path'
    return dict(sorted(found.items()))


def git_state(store):
    # A single bounded command restricted to this workspace, including when nested in a larger repo.
    # Never scan unrelated sibling projects in a parent checkout.
    try:
        # Avoid inherited MCP stdin and pipe-reader deadlocks on Windows. A regular temporary
        # output file also bounds the amount returned when Git metadata is unexpectedly large.
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(store.workspace),
                'status', '--porcelain=v2', '--branch', '--untracked-files=all', '--', '.'],
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL, timeout=3,
                close_fds=True, check=False, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            output.seek(0); metadata = output.read(64000).decode('utf-8', errors='replace')
        if result.returncode != 0: raise ValueError('Git metadata unavailable')
        lines = metadata.splitlines(); head = None; branch = None
        for line in lines:
            if line.startswith('# branch.oid '): head = line[len('# branch.oid '):]
            if line.startswith('# branch.head '): branch = line[len('# branch.head '):]
        return {'head': None if head == '(initial)' else head, 'branch': branch,
                'status': '\n'.join(line for line in lines if not line.startswith('# '))[:64000],
                'available': True, 'status_scope': 'workspace_only'}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'head': None, 'branch': None, 'status': None, 'available': False,
                'reason': 'not_git_or_metadata_unavailable'}


def tombstoned(db, snapshot_id):
    return db.execute("SELECT 1 FROM product_objects WHERE kind='snapshot_expiry' AND json_extract(data,'$.snapshot_id')=?", (snapshot_id,)).fetchone() is not None


def blob(store, snapshot, entry):
    root = safe_root(store); storage = snapshot['data']['storage_id']
    if not re.fullmatch('[a-f0-9]{32}', storage) or not re.fullmatch('[a-f0-9]{64}', entry.get('sha256', '')):
        raise ValueError('Invalid snapshot content reference')
    folder = root / storage; path = folder / entry['sha256']
    if linked_path(folder) or linked_path(path): raise ValueError('Linked snapshot content')
    with path.open('rb') as stream: raw = stream.read(FILE_LIMIT + 1)
    if len(raw) > FILE_LIMIT or hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('Snapshot content missing or changed')
    return raw


def remove_contents(store, db, row, reason):
    if tombstoned(db, row['id']): return
    root = safe_root(store); storage = row['data']['storage_id']
    if not re.fullmatch('[a-f0-9]{32}', storage): raise ValueError('Invalid snapshot directory')
    folder = root / storage
    if linked_path(folder): raise ValueError('Linked snapshot directory')
    if folder.exists():
        for path in folder.iterdir():
            if not re.fullmatch('[a-f0-9]{64}', path.name) or linked_path(path) or not path.is_file():
                raise ValueError('Unexpected snapshot storage content')
            path.unlink()
        folder.rmdir()
    ps.put(store, db, row['task'], 'snapshot_expiry', {'snapshot_id': row['id'],
        'reason': reason, 'content_available': False, 'hashes_and_history_retained': True})


def cleanup(store, db):
    root = safe_root(store)
    for r in db.execute("SELECT * FROM product_objects WHERE kind='code_snapshot'").fetchall():
        row = ps.get(db, r['id'])
        if time.time() - row['data']['captured_at'] > RETENTION_SECONDS:
            remove_contents(store, db, row, 'retention_expired')
    # Recover abandoned content from a rolled-back capture, never live referenced snapshots.
    referenced = {r['data']['storage_id'] for t in db.execute('SELECT task FROM product_tasks')
                  for r in ps.objects(db, t['task'], 'code_snapshot')}
    for folder in root.iterdir():
        if folder.name in referenced: continue
        if re.fullmatch('[a-f0-9]{32}', folder.name) and not linked_path(folder) and folder.is_dir():
            for file in folder.iterdir():
                if re.fullmatch('[a-f0-9]{64}', file.name) and file.is_file() and not linked_path(file): file.unlink()
            if not any(folder.iterdir()): folder.rmdir()
    return sum(p.stat().st_size for d in root.iterdir() if d.is_dir() and not linked_path(d)
               for p in d.iterdir() if p.is_file() and not linked_path(p))


def collect(store, db, task_id, scopes, excluded_paths, phase, expectation_id, unknown=False, parent_id=None, timing=None):
    scopes = sorted(set(normalize(p) for p in scopes)); excluded_paths = sorted(set(normalize(p) for p in excluded_paths))
    used = cleanup(store, db); root = safe_root(store); storage = uuid.uuid4().hex
    folder = root / storage; folder.mkdir(); total = 0; files = {}
    for relative, reason in enumerate_paths(store, scopes, excluded_paths).items():
        entry = {'path': relative, 'status': reason or 'captured'}
        if not reason:
            try:
                path = workspace_path(store, relative); before = path.stat()
                with path.open('rb') as stream: raw = stream.read(FILE_LIMIT + 1)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                    entry['status'] = 'concurrent_change_during_capture'
                elif len(raw) > FILE_LIMIT: entry['status'] = 'large_file'
                elif b'\0' in raw: entry['status'] = 'binary_file'
                else:
                    text = raw.decode('utf-8-sig')
                    if SECRET_CONTENT.search(text): entry['status'] = 'sensitive_content'
                    elif total + len(raw) > SNAPSHOT_LIMIT or used + total + len(raw) > PROJECT_LIMIT:
                        entry['status'] = 'storage_quota'
                    elif unknown: entry['status'] = 'no_pre_edit_baseline'
                    else:
                        digest = hashlib.sha256(raw).hexdigest()
                        target = folder / digest
                        if not target.exists(): target.write_bytes(raw)
                        total += len(raw); entry.update(sha256=digest, bytes=len(raw))
            except UnicodeError: entry['status'] = 'non_utf8_text'
            except (OSError, ValueError): entry['status'] = 'unreadable_or_unsafe'
        files[relative] = entry
    return ps.put(store, db, task_id, 'code_snapshot', {'storage_id': storage, 'scopes': scopes,
        'excluded_paths': excluded_paths, 'files': files, 'bytes': total, 'phase': phase,
        'workspace_identity': fingerprint(str(store.workspace)), 'workspace': str(store.workspace),
        'captured_at': time.time(), 'git': git_state(store), 'expectation_id': expectation_id,
        'parent_id': parent_id, 'timing': timing, 'timing_declared_by': 'agent',
        'attribution': 'workspace_changes_cannot_be_attributed_to_a_single_actor'})


def baseline_chain(db, row):
    result = []; seen = set()
    while row:
        if row['id'] in seen: raise ValueError('Invalid baseline chain')
        seen.add(row['id']); result.append(row)
        parent = row['data'].get('parent_id')
        row = ps.get(db, parent, 'code_snapshot', task_id=row['task']) if parent else None
    return list(reversed(result))


def baseline_files(db, row):
    files = {}; scopes = []; exclusions = []
    for segment in baseline_chain(db, row):
        scopes += segment['data']['scopes']; exclusions += segment['data']['excluded_paths']
        for path, entry in segment['data']['files'].items():
            files.setdefault(path, (segment, entry))
    return files, sorted(set(scopes)), sorted(set(exclusions))


def differences(store, db, baseline, end):
    before, scopes, exclusions = baseline_files(db, baseline); changes = []; uninspected = []
    for path in sorted(set(before) | set(end['data']['files'])):
        old_pair = before.get(path); old = old_pair[1] if old_pair else None
        new = end['data']['files'].get(path)
        if (old and old['status'] not in ('captured', 'absent_at_capture')) or (new and new['status'] not in ('captured', 'absent_at_capture')):
            uninspected.append({'path': path, 'before': old['status'] if old else 'absent', 'after': new['status'] if new else 'absent'}); continue
        a = old.get('sha256') if old else None; b = new.get('sha256') if new else None
        if old_pair and a and tombstoned(db, old_pair[0]['id']):
            uninspected.append({'path': path, 'reason': 'snapshot_content_unavailable'}); continue
        if a == b: continue
        try:
            if old_pair and tombstoned(db, old_pair[0]['id']): raise ValueError('Baseline expired')
            left = blob(store, old_pair[0], old).decode('utf-8-sig') if a else ''
            right = blob(store, end, new).decode('utf-8-sig') if b else ''
            diff = ''.join(difflib.unified_diff(left.splitlines(True), right.splitlines(True), fromfile='before/' + path, tofile='after/' + path))
            changes.append({'path': path, 'kind': 'added' if not a else 'deleted' if not b else 'modified',
                'before_sha256': a, 'after_sha256': b, 'diff': diff[:64000], 'diff_truncated': len(diff) > 64000})
        except (OSError, ValueError): uninspected.append({'path': path, 'reason': 'snapshot_content_unavailable'})
    return {'changes': changes, 'uninspected': uninspected, 'scopes': scopes, 'excluded_paths': exclusions,
            'outside_scope': 'not_inspected', 'attribution': 'observed_workspace_change_only'}


def current_files(store, snapshot):
    data = snapshot['data']; states = {}; total = 0
    for relative, reason in enumerate_paths(store, data['scopes'], data['excluded_paths']).items():
        if reason:
            states[relative] = {'status': reason}; continue
        try:
            with workspace_path(store, relative).open('rb') as stream: raw = stream.read(FILE_LIMIT + 1)
            reason = None
            if len(raw) > FILE_LIMIT: reason = 'large_file'
            elif b'\0' in raw: reason = 'binary_file'
            else:
                text = raw.decode('utf-8-sig')
                if SECRET_CONTENT.search(text): reason = 'sensitive_content'
            if not reason and (total + len(raw) > SNAPSHOT_LIMIT or data['files'].get(relative, {}).get('status') == 'storage_quota'):
                reason = 'storage_quota'
            if reason: states[relative] = {'status': reason}
            else:
                total += len(raw)
                states[relative] = {'status': 'captured', 'sha256': hashlib.sha256(raw).hexdigest()}
        except UnicodeError: states[relative] = {'status': 'non_utf8_text'}
        except (OSError, ValueError): states[relative] = {'status': 'unreadable_or_unsafe'}
    return states


def freshness(store, db, row):
    if tombstoned(db, row['id']): return ['snapshot_content_unavailable']
    actual = current_files(store, row); reasons = []
    for path in set(actual) | set(row['data']['files']):
        old = row['data']['files'].get(path, {}); new = actual.get(path, {})
        if old.get('sha256') != new.get('sha256'):
            reasons.append('workspace_changed:' + path)
        elif bool(old) != bool(new) and old.get('status') != 'absent_at_capture' and new.get('status') != 'absent_at_capture':
            reasons.append('scope_inventory_changed:' + path)
        elif old.get('status') == 'captured':
            try: blob(store, row, old)
            except (OSError, ValueError): reasons.append('snapshot_content_unavailable:' + path)
    return reasons


def execute(service, request):
    request = validate('snapshot', request); action = request['action']; task_id = request['task_id']
    def handler(store, db, ctx):
        if action == 'inspect':
            return collect(store,db,task_id,request['scopes'],request.get('excluded_paths',[]),'current_review',None)
        if action == 'capture':
            expectation = ps.get(db, request['expectation_id'], 'expectation', task_id=task_id)
            from .experience import current_reasons
            if current_reasons(store, db, expectation['data']): raise ValueError('Expectation is stale before development')
            return collect(store, db, task_id, request['scopes'], request.get('excluded_paths', []), 'start', expectation['id'])
        if action == 'status':
            row = ps.get(db, request['snapshot_id'], 'code_snapshot', task_id=task_id)
            available = not tombstoned(db, row['id'])
            if available:
                for entry in row['data']['files'].values():
                    if entry['status'] != 'captured': continue
                    try: blob(store, row, entry)
                    except (OSError, ValueError): available = False; break
            return {**row, 'content_available': available}
        if action == 'prune':
            for ident in request['snapshot_ids']:
                remove_contents(store, db, ps.get(db, ident, 'code_snapshot', task_id=task_id), 'explicit_cleanup')
            return {'pruned': request['snapshot_ids'], 'hashes_and_history_retained': True}
        baseline = ps.get(db, request['baseline_id'], 'code_snapshot', task_id=task_id)
        if baseline['data']['phase'] not in ('start', 'extension'):
            raise ValueError('Development requires a pre-edit baseline')
        before, scopes, exclusions = baseline_files(db, baseline)
        if action == 'extend':
            new_scopes = [normalize(p) for p in request['scopes']]
            if any(s == '.' or old == '.' or s == old or s.startswith(old.rstrip('/') + '/') or old.startswith(s.rstrip('/') + '/')
                   for s in new_scopes for old in scopes):
                raise ValueError('Extension must add disjoint scopes; existing baseline cannot be replaced')
            return collect(store, db, task_id, new_scopes, exclusions, 'extension', baseline['data']['expectation_id'],
                           unknown=request['timing'] == 'already_modified', parent_id=baseline['id'], timing=request['timing'])
        end = collect(store, db, task_id, scopes, exclusions, 'end', baseline['data']['expectation_id'])
        end_row = ps.get(db, end['id'])
        return ps.put(store, db, task_id, 'code_comparison', {'baseline_id': baseline['id'], 'end_id': end['id'],
            'expectation_id': baseline['data']['expectation_id'], **differences(store, db, baseline, end_row)})
    result=ps.run(service, request, handler)
    from .product_workflow import progress
    return {**result,'workflow':progress(service.store(),task_id)}
