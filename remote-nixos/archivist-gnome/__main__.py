import sys
from .app import ArchivistApp

def main():
    app = ArchivistApp()
    sys.exit(app.run(sys.argv))

if __name__ == "__main__":
    main()
