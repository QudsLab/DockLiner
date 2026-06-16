# this script will clean the cache files befor any nessassary build

# clean __pycache__ folder from NextSSL folder and its subfolders
import os
import shutil
def clean_pycache():
    for root, dirs, _ in os.walk('.', topdown=False):
        if '__pycache__' in dirs:
            pycache_dir = os.path.join(root, '__pycache__')
            shutil.rmtree(pycache_dir)
            print(f"Removed: {pycache_dir}")

clean_pycache()
