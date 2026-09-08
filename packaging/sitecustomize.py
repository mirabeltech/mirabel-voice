"""Bundle-only long-path support; does not change Windows policy or the registry."""
import os
import sys

if os.name == 'nt':
    def extended(path):
        path = os.path.abspath(path)
        if path.startswith('\\\\?\\'):
            return path
        if path.startswith('\\\\'):
            return '\\\\?\\UNC\\' + path[2:]
        return '\\\\?\\' + path
    sys.path[:] = [extended(path) for path in sys.path if path]
