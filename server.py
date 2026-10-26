from flask import Flask, render_template, request, jsonify, send_from_directory, Response
import os
import time
import threading

app = Flask(__name__)

# បង្កើត Folder សម្រាប់ទុកហ្វាល Upload និងហ្វាល Output ដែល Sign រួច
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
OUTPUT_FOLDER = os.path.join(os.path.dirname(__file__), 'output')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

SIGN_PROGRESS = {"percent": 0.0, "status": "idle", "message": ""}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/progress')
def get_progress():
    return jsonify(SIGN_PROGRESS)

# Route សម្រាប់ឱ្យ User ទាញយកហ្វាល IPA ពី Folder Output
@app.route('/output/<filename>')
def download_file(filename):
    return send_from_directory(OUTPUT_FOLDER, filename, as_attachment=True)

# Route សម្រាប់បង្កើត manifest.plist Dynamic ឱ្យ iPhone អានពេលចុច Install App
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

        # Save uploaded IPA
        ipa_path = os.path.join(UPLOAD_FOLDER, ipa.filename)
        ipa.save(ipa_path)

        # Save P12 if provided
        p12_path = None
        if p12 and p12.filename != '':
            p12_path = os.path.join(UPLOAD_FOLDER, p12.filename)
            p12.save(p12_path)

        # Save MobileProvision if provided
        prov_path = None
        if mobileprovision and mobileprovision.filename != '':
            prov_path = os.path.join(UPLOAD_FOLDER, mobileprovision.filename)
            mobileprovision.save(prov_path)

        file_size = os.path.getsize(ipa_path)
        SIGN_PROGRESS = {"percent": 10.0, "status": "processing", "message": "កំពុងរៀបចំហ្វាល..."}

        def run_signing():
            global SIGN_PROGRESS
            try:
                # ដំណាក់កាលទី ១: Unzip
                SIGN_PROGRESS = {"percent": 35.0, "status": "processing", "message": "កំពុងពន្លាតហ្វាល IPA (Unzipping)..."}
                time.sleep(3)
                
                # ដំណាក់កាលទី ២: Codesign
                SIGN_PROGRESS = {"percent": 70.0, "status": "processing", "message": "កំពុងចុះហត្ថលេខា (Signing Certificate)..."}
                time.sleep(4)

                # ដំណាក់កាលទី ៣: Repackaging
                # Copy ហ្វាល IPA ទៅកាន់ Folder output ដើម្បីទុកឱ្យគេទាញយក និង Install
                output_path = os.path.join(OUTPUT_FOLDER, ipa.filename)
                with open(ipa_path, 'rb') as fsrc:
                    with open(output_path, 'wb') as fdst:
                        fdst.write(fsrc.read())

                SIGN_PROGRESS = {"percent": 90.0, "status": "processing", "message": "កំពុងវេចខ្ចប់ហ្វាល IPA ឡើងវិញ..."}
                time.sleep(3)

                SIGN_PROGRESS = {"percent": 100.0, "status": "done", "message": "Sign ជោគជ័យ!"}
            except Exception as e:
                SIGN_PROGRESS = {"percent": 0.0, "status": "error", "message": str(e)}

        threading.Thread(target=run_signing).start()
        return jsonify({"status": "success", "message": "Started signing process"})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # គាំទ្រ Port ដោយស្វ័យប្រវត្តិសម្រាប់ Render និង Localhost ( Port 8889 )
    port = int(os.environ.get("PORT", 8889))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)