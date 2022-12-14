import os
import time
import argparse
from tempfile import TemporaryDirectory

from calx.dtypes import *
from calx.utils import read_environ
from calx.scripts.config import load_config
from calx.scripts.config.check import check_pipeline_configs
from calx.scripts.containers import (
    build,
    spawn_container,
    BaseContainer,
    LocalContainer,
)


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="run all steps defined in pipeline",
    )
    parser.add_argument(
        "-c",
        "--container",
        type=str,
        default="local",
        help="container to be used for running step",
    )
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        default="pipeline.yaml",
        help="the path to pipeline.yaml file",
    )
    parser.add_argument(
        "-s",
        "--step",
        type=str,
        default=None,
        help="run single pipeline step",
    )
    parser.add_argument(
        "workdir",
        type=str,
        help="working directory",
    )

    return parser.parse_args()


def run_step(step: str, args: Namespace, conf: Config) -> BaseContainer:
    step_conf = conf["steps"][step]
    step_type = step_conf["type"].lower()
    container_type = args.container if step_type != "docker" else "local"
    envlist = read_environ(step_conf.get("envfile"), args.workdir)
    output = step_conf.get("output")

    return spawn_container(
        container_type, step, args.file, args.workdir, envlist, output
    )


def run_pipeline(args: Namespace, conf: Config):
    running = {}
    queued = {}
    to_pop = []

    # prepare queue
    for c in conf["dag"]:
        queued[c["name"]] = {
            "step": c["step"],
            "dependencies": set(c["dependencies"]),
        }

    while len(queued) > 0:
        # move job from queue to running
        to_pop.clear()
        for name, c in queued.items():
            if not c["dependencies"]:
                running[name] = run_step(c["step"], args, conf)
                to_pop.append(name)

        for qname in to_pop:
            del queued[qname]

        # remove finished process
        to_pop.clear()
        while True:
            for pname in running:
                if running[pname].is_finished():
                    to_pop.append(pname)

            if to_pop:
                break

            time.sleep(0.5)

        for pname in to_pop:
            with open(os.path.join(os.environ["CALX_TMPDIR"], pname), "w") as fp:
                fp.write(running[pname].output())

            if isinstance(running[pname], LocalContainer) and running[pname]._output:
                os.remove(running[pname]._output)

            del running[pname]

            for qname in queued:
                queued[qname]["dependencies"].discard(pname)

    return


def run(args: Namespace, conf: Config):
    if args.all:
        _ = run_pipeline(args, conf)

    elif args.step:
        container = run_step(args.step, args, conf)
        container.wait()


def main():
    args = parse_arguments()
    conf = load_config(args.file, args.workdir)

    # == !DEBUG! ==
    print("[calx-run]")
    print(vars(args))
    print(conf)
    # =============

    with TemporaryDirectory(prefix="calx") as tmpdir:
        os.environ["CALX_TMPDIR"] = tmpdir

        check_pipeline_configs(conf)
        build(args, conf)
        run(args, conf)


# Note + Reminder:
# - containers spawned using LocalContainer will be based on args.workdir,
#   all runners (expect docker) should be based on this directory.
# - containers spawned using DockerContainer will be based on /usr/src/app
#   which is from args.workdir. The args.file file will be moved to
#   /tmp/calx-run/pipeline.yaml inside the docker container.
# - all paths inside args.file should be relative to args.workdir
