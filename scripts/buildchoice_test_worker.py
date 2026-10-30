"""Internal reporter; invoke the public collector instead."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from buildchoice.desktop.verification_worker import main
if __name__=='__main__':sys.exit(main())
