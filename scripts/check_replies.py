import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from outreach.check_replies import main


if __name__ == "__main__":
    main()
