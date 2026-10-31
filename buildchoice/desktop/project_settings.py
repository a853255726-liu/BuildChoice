"""Read per-project installation settings without creating or changing bindings."""
import json
import os
from pathlib import Path


def installation_home(home=None):
    return Path(home or os.environ.get('BUILDCHOICE_DATA') or Path.home()/'.buildchoice').resolve()


def selected_binding(home=None,workspace=None):
    home=installation_home(home);registry=home/'projects.json'
    if registry.is_file():
        value=json.loads(registry.read_text(encoding='utf-8'))
        if value.get('registry_version')!=1:raise ValueError('Invalid project registry')
        if workspace is not None:
            path=Path(workspace).resolve()
            matches=[v for v in value['projects'].values() if path.is_relative_to(Path(v['workspace']).resolve())]
            if not matches:raise ValueError('Project is not registered')
            return max(matches,key=lambda v:len(Path(v['workspace']).resolve().parts))
        return value['projects'][value['active_project']]
    return json.loads((home/'binding.json').read_text(encoding='utf-8'))


def project_config(name,home=None,workspace=None):
    try:
        value=selected_binding(home,workspace)
    except FileNotFoundError:
        if home is not None:raise ValueError('Installation is not initialized')
        return None
    return Path(value['profile_home'])/'configs'/name if value.get('profile_home') else None
