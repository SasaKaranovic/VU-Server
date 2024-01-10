'''
Simple python script to dynamically add version tag to HTML files
'''

import os.path
from datetime import datetime

def apply_version_tag(filepath, tag_placeholder, tag_value):
    if not os.path.isfile(filepath):
        print(f'Not a file! {filepath}')
        return False

    with open(filepath, 'r') as template:
        content = template.read()

    if tag_placeholder in content:
        print(f"Patching `{filepath}` with tag `{tag_value}`")
    content = content.replace(tag_placeholder, version_tag)

    with open(filepath, 'w') as stamped:
        Writing data to a file
        stamped.write(content)

    return True


if __name__ == '__main__':
    # Add version tag to HTML template
    dt = datetime.now()
    version_tag = dt.strftime('%Y%m%d')
    footer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'www', 'views', 'footer.html')
    apply_version_tag(footer_path, '{{VU_VERSION}}', version_tag)

    # Update installer version
    version_major = dt.strftime('%Y')
    version_minor = dt.strftime('%m')
    version_build = dt.strftime('%d')
    installer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'installer', 'install.nsi')
    apply_version_tag(installer_path, '{{VU_VERSION_MAJOR}}', version_major)
    apply_version_tag(installer_path, '{{VU_VERSION_MINOR}}', version_minor)
    apply_version_tag(installer_path, '{{VU_VERSION_BUILD}}', version_build)
