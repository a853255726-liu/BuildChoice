"""All four lifecycle events enter this dependency-free, reviewable launcher."""
from launch import run
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('--data-home')
raise SystemExit(run('hook',parser.parse_args().data_home))
