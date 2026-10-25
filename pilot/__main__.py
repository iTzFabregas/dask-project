import argparse
import copy
import os
import sys
from pathlib import Path

from .common import cgroup_state, read_json, versions, write_json


def main():
    parser = argparse.ArgumentParser(description='SSC0954 Grupo 05: executar, validar, medir, repetir, analisar e demonstrar')
    commands = parser.add_subparsers(dest='command', required=True)
    server = commands.add_parser('serve', help='Serve exported results after measurements')
    server.add_argument('--directory', default='/exports')
    server.add_argument('--bind', default='127.0.0.1')
    server.add_argument('--port', type=int, default=5285)
    env = commands.add_parser('environment', help='Record actual resources/versions without a benchmark')
    env.add_argument('--output', default='/exports/evidence/environment.json')
    for command, default in [('smoke', 'configs/smoke.json'), ('pilot', 'configs/pilot.json'),
                             ('scenario', 'configs/pilot.json'), ('host-check', 'configs/smoke.json')]:
        sub = commands.add_parser(command)
        sub.add_argument('--config', default=default)
        sub.add_argument('--experiment', required=True)
        sub.add_argument('--export-dir', default='/exports')
        if command in ('smoke', 'pilot'):
            sub.add_argument('--workers', type=int)
            sub.add_argument('--partitions', type=int)
        if command == 'scenario':
            sub.add_argument('--volume', choices=['small', 'medium', 'large'], required=True)
            sub.add_argument('--approach', choices=['pandas', 'dask'], required=True)
            sub.add_argument('--workers', type=int, default=2)
            sub.add_argument('--partitions', type=int, default=16)
            sub.add_argument('--repetitions', type=int, default=5)
        if command == 'host-check':
            sub.add_argument('--allow-host-check', action='store_true', required=True)
    for cmd in ('analyze', 'export'):
        sub = commands.add_parser(cmd)
        sub.add_argument('--experiment-path', required=True)
        sub.add_argument('--export-dir', default='/exports')
    demo = commands.add_parser('demo-cluster')
    demo.add_argument('--workers', choices=[1, 2], type=int, default=2)
    trial = commands.add_parser('_trial')
    trial.add_argument('spec')
    empty = commands.add_parser('empty-page')
    empty.add_argument('--export-dir', default='/exports')
    args = parser.parse_args()
    if args.command == 'serve':
        from .web import serve
        serve(args.directory, args.bind, args.port)
        return 0
    if args.command == '_trial':
        from .trial import execute
        return execute(args.spec)
    if args.command == 'environment':
        write_json(args.output, {'resources': cgroup_state(), 'versions': versions(),
                                'environment': os.environ.get('EXPERIMENT_ENV', 'PC local')})
        print(args.output)
        return 0
    if args.command == 'demo-cluster':
        import time
        from distributed import Client, LocalCluster
        from .common import roots, verify_limits
        verify_limits(cgroup_state())
        with LocalCluster(n_workers=args.workers, threads_per_worker=1, processes=True,
                          host='0.0.0.0', protocol='tcp', dashboard_address=':8787',
                          memory_limit=os.environ.get('WORKER_MEMORY_MIB', '768') + 'MiB',
                          local_directory=str(roots()[2])) as cluster, Client(cluster) as client:
            print('Dashboard ready on internal 8787; published 5185 by default. Demo only, no benchmark.', flush=True)
            while True:
                time.sleep(1)
    from .analysis import analyze, empty_page, export
    if args.command == 'empty-page':
        empty_page(args.export_dir)
        return 0
    if args.command in ('analyze', 'export'):
        path = Path(args.experiment_path)
        if args.command == 'analyze':
            print(analyze(path))
        print(export(path, args.export_dir))
        return 0
    from .runner import override_dask_scenarios, pilot_with_gates, run_config
    config = read_json(args.config)
    smoke_config = None
    if args.command in ('smoke', 'pilot'):
        config = override_dask_scenarios(config, args.workers, args.partitions)
        if args.command == 'pilot':
            smoke_config = override_dask_scenarios(
                read_json('configs/smoke.json'), args.workers, args.partitions)
    if args.command == 'scenario':
        config = copy.deepcopy(config)
        config.update(mode='scenario', blocks=args.repetitions)
        config['volumes'] = {args.volume: config['volumes'][args.volume]}
        config['scenarios'] = [{'volume': args.volume, 'approach': args.approach,
                                'workers': args.workers if args.approach == 'dask' else 0,
                                'partitions': args.partitions if args.approach == 'dask' else 0}]
    if args.command == 'host-check':
        config['mode'] = 'host-check'
    try:
        path = pilot_with_gates(config, args.experiment, smoke_config) if args.command == 'pilot' else run_config(
            config, args.experiment, allow_host=args.command == 'host-check')
    except Exception:
        # Export failed sessions too, preserving every attempt and honest incomplete status.
        from .common import roots
        path = roots()[1] / config['mode'] / args.experiment
        if (path / 'experiment.json').exists():
            print(analyze(path))
            print(export(path, args.export_dir))
        raise
    print(analyze(path))
    print(export(path, args.export_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
