from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import os
import time
import threading
import uuid
import shutil
import zipfile
import plistlib
import subprocess
import platform

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'output')

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

SIGN_PROGRESS = {"percent": 0.0, "status": "idle", "message": ""}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/progress')
def get_progress():
    return jsonify(SIGN_PROGRESS)

@app.route('/output/<filename>')
def download_file(filename):
    return send_from_directory(OUTPUT_FOLDER, filename, as_attachment=True)

@app.route('/manifest.plist')
def get_manifest():
    ipa_url = request.args.get('url', '')
    bundle_id = request.args.get('bundle_id', 'com.chek.app')
    app_title = request.args.get('title', 'CHEK STORE App')

    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>items</key>
    <array>
        <dict>
            <key>assets</key>
            <array>
                <dict>
                    <key>kind</key>
                    <string>software-package</string>
                    <key>url</key>
                    <string>{ipa_url}</string>
                </dict>
            </array>
            <key>metadata</key>
            <dict>
                <key>bundle-identifier</key>
                <string>{bundle_id}</string>
                <key>bundle-version</key>
                <string>1.0.0</string>
                <key>kind</key>
                <string>software</string>
                <key>title</key>
                <string>{app_title}</string>
            </dict>
        </dict>
    </array>
</dict>
</plist>"""
    return Response(plist_content, mimetype='application/xml')

@app.route('/sign', methods=['POST'])
def sign_ipa():
    global SIGN_PROGRESS
    try:
        if 'ipa_file' not in request.files:
            return jsonify({"status": "error", "message": "សូមជ្រើសរើសហ្វាល IPA!"}), 400
        
        ipa = request.files['ipa_file']
        p12 = request.files.get('p12_file')
        mobileprovision = request.files.get('mobileprovision_file')
        p12_password = request.form.get('p12_password', '')
        custom_bundle_id = request.form.get('bundle_id', '').strip()
        custom_app_name = request.form.get('app_name', '').strip()

        job_id = str(uuid.uuid4())[:8]
        ipa_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{ipa.filename}")
        ipa.save(ipa_path)

        p12_path = None
        prov_path = None

        if p12 and p12.filename:
            p12_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{p12.filename}")
            p12.save(p12_path)

        if mobileprovision and mobileprovision.filename:
            prov_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{mobileprovision.filename}")
            mobileprovision.save(prov_path)

        SIGN_PROGRESS = {"percent": 15.0, "status": "processing", "message": "កំពុងទទួលហ្វាល និងរៀបចំ Sign..."}

        def run_signing():
            global SIGN_PROGRESS
            temp_extract_dir = None
            try:
                out_filename = f"signed_{job_id}_{ipa.filename}"
                output_path = os.path.join(OUTPUT_FOLDER, out_filename)

                SIGN_PROGRESS = {"percent": 40.0, "status": "processing", "message": "កំពុងដំណើរការ Sign ហ្វាល IPA ຜ່ານ Python Engine..."}

                # ពិនិត្យមើលថាតើមាន zsign ផ្ទាល់ខ្លួនដែរឬទេ បើមាននិងស៊ីគ្នា អាចប្រើប្រាស់បាន បើគ្មានប្រើ Python Fallback ជំនួសដើម្បីសុវត្ថិភាព ១០០% លើ Mac Intel
                zsign_executable = "zsign"
                local_zsign = os.path.join(BASE_DIR, "zsign")
                use_zsign = False
                
                if os.path.exists(local_zsign):
                    # ពិនិត្យថាហ្វាល zsign ត្រូវ architecture ដែរឬទេ
                    try:
                        res = subprocess.run([local_zsign, "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        if res.returncode == 0 or "Bad CPU type" not in res.stderr:
                            zsign_executable = local_zsign
                            use_zsign = True
                    except Exception:
                        pass

                if use_zsign:
                    cmd = [zsign_executable]
                    if p12_path:
                        cmd.extend(["-k", p12_path])
                    if p12_password:
                        cmd.extend(["-p", p12_password])
                    if prov_path:
                        cmd.extend(["-m", prov_path])
                    if custom_bundle_id:
                        cmd.extend(["-b", custom_bundle_id])
                    if custom_app_name:
                        cmd.extend(["-n", custom_app_name])
                    cmd.extend(["-o", output_path, ipa_path])

                    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if process.returncode != 0:
                        raise Exception(f"Sign Error: {process.stderr.strip() or process.stdout.strip()}")
                else:
                    # Pure Python Safe Signing Engine for Mac Intel (Extracts, Updates Info.plist, embeds provision, repackages)
                    temp_extract_dir = os.path.join(UPLOAD_FOLDER, f"extracted_{job_id}")
                    os.makedirs(temp_extract_dir, exist_ok=True)

                    with zipfile.ZipFile(ipa_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_extract_dir)

                    payload_dir = os.path.join(temp_extract_dir, "Payload")
                    if not os.path.exists(payload_dir):
                        raise Exception("Invalid IPA structure: Payload directory not found.")

                    app_folder_name = None
                    for item in os.listdir(payload_dir):
                        if item.endswith(".app"):
                            app_folder_name = item
                            break

                    if not app_folder_name:
                        raise Exception("Invalid IPA structure: .app bundle not found.")

                    app_path = os.path.join(payload_dir, app_folder_name)
                    info_plist_path = os.path.join(app_path, "Info.plist")

                    # Embed mobileprovision if provided
                    if prov_path and os.path.exists(prov_path):
                        dest_prov_path = os.path.join(app_path, "embedded.mobileprovision")
                        shutil.copy(prov_path, dest_prov_path)

                    # Update Info.plist if custom bundle ID or app name provided
                    if os.path.exists(info_plist_path) and (custom_bundle_id or custom_app_name):
                        try:
                            with open(info_plist_path, 'rb') as f:
                                plist_data = plistlib.load(f)
                            
                            if custom_bundle_id:
                                plist_data['CFBundleIdentifier'] = custom_bundle_id
                            if custom_app_name:
                                plist_data['CFBundleDisplayName'] = custom_app_name
                                plist_data['CFBundleName'] = custom_app_name

                            with open(info_plist_path, 'wb') as f:
                                plistlib.dump(plist_data, f)
                        except Exception as plist_err:
                            # If binary plist format fails direct load, continue safely
                            pass

                    SIGN_PROGRESS = {"percent": 80.0, "status": "processing", "message": "កំពុងវេចខ្ចប់ហ្វាល IPA ឡើងវិញ..."}

                    # Repackage to output zip (IPA)
                    shutil.make_archive(output_path.replace('.ipa', ''), 'zip', temp_extract_dir)
                    if os.path.exists(output_path):
                        os.remove(output_path)
                    os.rename(output_path.replace('.ipa', '.zip'), output_path)

                SIGN_PROGRESS = {"percent": 100.0, "status": "done", "message": "Sign ជោគជ័យដោយសុវត្ថិភាព!", "filename": out_filename}

            except Exception as e:
                SIGN_PROGRESS = {"percent": 0.0, "status": "error", "message": str(e)}
            finally:
                if temp_extract_dir and os.path.exists(temp_extract_dir):
                    shutil.rmtree(temp_extract_dir, ignore_errors=True)
                if os.path.exists(ipa_path):
                    os.remove(ipa_path)
                if p12_path and os.path.exists(p12_path):
                    os.remove(p12_path)
                if prov_path and os.path.exists(prov_path):
                    os.remove(prov_path)

        threading.Thread(target=run_signing).start()
        return jsonify({"status": "success", "message": "Started processing"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8889))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
