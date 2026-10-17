"""Request shutdown from the local manager, without process-name killing."""
import sys
from app_launcher import main
if __name__=="__main__":
    sys.argv.append("--stop")
    raise SystemExit(main())
