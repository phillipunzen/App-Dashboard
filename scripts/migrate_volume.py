"""Migrate an existing Docker volume to AppDashboard without deleting the source."""
import argparse
import subprocess


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description='Vorhandenes Dashboard-Volume nach AppDashboard kopieren.')
    parser.add_argument('--source', required=True, help='Name des bisherigen Docker-Volumes')
    parser.add_argument('--target', default='appdashboard_data')
    parser.add_argument('--image', default='ghcr.io/phillipunzen/appdashboard:latest')
    args = parser.parse_args()
    if args.source == args.target:
        parser.error('Quelle und Ziel müssen verschieden sein.')
    docker('volume', 'inspect', args.source)
    if docker('ps', '--quiet', '--filter', f'volume={args.source}'):
        parser.error('Stoppe zuerst alle Container, die das Quell-Volume verwenden.')
    if docker('ps', '--quiet', '--filter', f'volume={args.target}'):
        parser.error('Stoppe zuerst alle Container, die das Ziel-Volume verwenden.')
    # A target volume may exist only if it is empty; the runtime module validates this.
    existing = docker('volume', 'ls', '--format', '{{.Name}}').splitlines()
    if args.target not in existing:
        docker('volume', 'create', '--label', 'com.appdashboard.managed=true', args.target)
    subprocess.run([
        'docker', 'run', '--rm', '--read-only', '--tmpfs', '/tmp', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges:true',
        '--mount', f'type=volume,source={args.source},target=/source,readonly',
        '--mount', f'type=volume,source={args.target},target=/data',
        '--entrypoint', 'python', args.image, '-m', 'app.migrate',
    ], check=True)
    print(f'Die Quelle bleibt erhalten. Ziel-Volume: {args.target}')


if __name__ == '__main__':
    main()
