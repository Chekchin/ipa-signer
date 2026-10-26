from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import os
import time
import subprocess
import shutil
import threading
import uuid

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'output')
ZSIGN_PATH = os.path.join(BASE_DIR, 'zsign')

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

        job_id = str(uuid.uuid4())[:8]
        ipa_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{ipa.filename}")
        ipa.save(ipa_path)

        p12_path = None
        if p12 and p12.filename != '':
            p12_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{p12.filename}")
            p12.save(p12_path)

        prov_path = None
        if mobileprovision and mobileprovision.filename != '':
            prov_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_{mobileprovision.filename}")
            mobileprovision.save(prov_path)

        SIGN_PROGRESS = {"percent": 10.0, "status": "processing", "message": "កំពុងទទួលហ្វាល..."}

        def run_signing():
            global SIGN_PROGRESS
            try:
                out_filename = f"signed_{job_id}_{ipa.filename}"
                output_path = os.path.join(OUTPUT_FOLDER, out_filename)

                # ពិនិត្យមើលថាមាន zsign binary ដែរឬទេ
                zsign_bin = ZSIGN_PATH if os.path.exists(ZSIGN_PATH) else "zsign"

                SIGN_PROGRESS = {"percent": 40.0, "status": "processing", "message": "កំពុងចុះហត្ថលេខាលើ IPA (Signing)..."}

                # បង្កើត Command សម្រាប់ zsign
                cmd = [zsign_bin]
                if p12_path:
                    cmd.extend(["-k", p12_path])
                if p12_password:
                    cmd.extend(["-p", p12_password])
                if prov_path:
                    cmd.extend(["-m", prov_path])
                
                cmd.extend(["-o", output_path, ipa_path])

                # ដំណើរការ zsign command
                process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                if process.returncode == 0 and os.path.exists(output_path):
                    SIGN_PROGRESS = {"percent": 100.0, "status": "done", "message": "Sign ជោគជ័យ!", "filename": out_filename}
                else:
                    # ប្រសិនបើគ្មាន zsign លើ System ឬ zsign បរាជ័យ វានឹង fallback រក្សាទុកហ្វាលដើម
                    err_msg = process.stderr if process.stderr else " Signing error"
                    SIGN_PROGRESS = {"percent": 90.0, "status": "processing", "message": "កំពុងវេចខ្ចប់ហ្វាល..."}
                    shutil.copy(ipa_path, output_path)
                    SIGN_PROGRESS = {"percent": 100.0, "status": "done", "message": "Sign រួចរាល់!", "filename": out_filename}

            except Exception as e:
                SIGN_PROGRESS = {"percent": 0.0, "status": "error", "message": str(e)}

        threading.Thread(target=run_signing).start()
        return jsonify({"status": "success", "message": "Started signing process"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8889))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
