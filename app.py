import os
import base64
import time
import json
from datetime import datetime
from flask import Flask, render_template, jsonify, request, send_from_directory
import uiautomator2 as u2
from PIL import Image
import io
from functools import wraps

app = Flask(__name__)
app.config['SAVED_SCRIPTS_DIR'] = 'saved_scripts'
app.config['STATIC_FOLDER'] = 'static'

# 确保保存脚本的目录存在
os.makedirs(app.config['SAVED_SCRIPTS_DIR'], exist_ok=True)
os.makedirs(os.path.join(app.config['STATIC_FOLDER'], 'css'), exist_ok=True)

# 存储设备连接和录制状态
device_connections = {}  # 设备连接对象
recording_sessions = {}  # 录制会话 {device_id: {actions: [], start_time: }}


# 工具函数：设备连接检查装饰器
def device_required(f):
    @wraps(f)
    def decorated_function(device_id, *args, **kwargs):
        if device_id not in device_connections:
            return jsonify({
                'success': False,
                'error': f'未连接到设备 {device_id}'
            })
        return f(device_id, *args, **kwargs)

    return decorated_function


# 工具函数：录制状态检查装饰器
def recording_required(f):
    @wraps(f)
    @device_required
    def decorated_function(device_id, *args, **kwargs):
        session = recording_sessions.get(device_id)
        if not session or session['start_time'] is None:
            return jsonify({
                'success': False,
                'error': f'设备 {device_id} 未在录制中'
            })
        return f(device_id, *args, **kwargs)

    return decorated_function


def get_device_list():
    """获取已连接的设备列表（修复了设备列表获取方法）"""
    try:
        # 使用uiautomator2正确的设备列表获取方法
        from uiautomator2 import connect_adb_wifi
        import subprocess
        import re

        # 通过adb命令获取设备列表
        result = subprocess.check_output(['adb', 'devices']).decode('utf-8')
        devices = re.findall(r'(\S+)\s+device', result)
        return devices
    except Exception as e:
        app.logger.error(f"获取设备列表失败: {str(e)}")
        return []


def generate_script_content(device_id, actions):
    """生成Python脚本内容"""
    script_lines = [
        'import uiautomator2 as u2',
        'import time',
        '',
        f"d = u2.connect('{device_id}')",
        "d.wait_ready(timeout=10.0)",
        ""
    ]

    # 添加操作
    prev_time = 0
    for action in actions:
        # 添加延迟（相对于上一个操作）
        delay = action['time'] - prev_time
        if delay > 0.1:  # 只添加明显的延迟
            script_lines.append(f"time.sleep({delay:.2f})")

        # 添加操作代码
        if action['type'] == 'click':
            script_lines.append(f"d.click({action['x']}, {action['y']})")
        elif action['type'] == 'swipe':
            script_lines.append(f"d.swipe({action['x1']}, {action['y1']}, {action['x2']}, {action['y2']})")

        prev_time = action['time']

    return '\n'.join(script_lines)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/devices')
def devices():
    try:
        devices = get_device_list()
        return jsonify({
            'success': True,
            'devices': devices
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/connect/<device_id>')
def connect(device_id):
    try:
        if device_id in device_connections:
            return jsonify({
                'success': True,
                'message': f'已连接到设备 {device_id}'
            })

        # 连接设备
        d = u2.connect(device_id)
        device_connections[device_id] = d

        # 初始化录制会话
        recording_sessions[device_id] = {
            'actions': [],
            'start_time': None
        }

        return jsonify({
            'success': True,
            'message': f'成功连接到设备 {device_id}'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/disconnect/<device_id>')
def disconnect(device_id):
    try:
        if device_id in device_connections:
            del device_connections[device_id]

        if device_id in recording_sessions:
            del recording_sessions[device_id]

        return jsonify({
            'success': True,
            'message': f'已断开设备 {device_id} 的连接'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/screenshot/<device_id>')
@device_required
def screenshot(device_id):
    try:
        d = device_connections[device_id]
        img = d.screenshot()

        # 将图片转换为base64
        buf = io.BytesIO()
        img.save(buf, format='JPEG')
        img_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')

        return jsonify({
            'success': True,
            'image': img_base64
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/start_recording/<device_id>')
@device_required
def start_recording(device_id):
    try:
        # 初始化录制会话
        recording_sessions[device_id] = {
            'actions': [],
            'start_time': time.time()
        }

        return jsonify({
            'success': True,
            'message': f'开始录制设备 {device_id} 的操作'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/stop_recording/<device_id>')
@device_required
def stop_recording(device_id):
    try:
        if device_id not in recording_sessions:
            return jsonify({
                'success': False,
                'error': f'设备 {device_id} 未在录制中'
            })

        # 只是标记停止，保留操作记录
        recording_sessions[device_id]['start_time'] = None

        return jsonify({
            'success': True,
            'message': f'已停止录制设备 {device_id} 的操作'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/record_action/<device_id>', methods=['POST'])
@recording_required
def record_action(device_id):
    try:
        session = recording_sessions[device_id]
        action = request.json
        current_time = time.time()

        action['time'] = current_time - session['start_time']
        session['actions'].append(action)

        # 添加日志：打印当前操作和累计操作数
        app.logger.info(f"设备 {device_id} 记录操作: {action}，累计 {len(session['actions'])} 条")

        # 记录相对时间（自录制开始以来的秒数）
        action['time'] = current_time - session['start_time']
        session['actions'].append(action)

        # 在设备上执行操作（给用户反馈）
        d = device_connections[device_id]
        if action['type'] == 'click':
            d.click(action['x'], action['y'])
        elif action['type'] == 'swipe':
            d.swipe(action['x1'], action['y1'], action['x2'], action['y2'])

        return jsonify({
            'success': True,
            'message': '操作已记录'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/save_script/<device_id>')
@device_required
def save_script(device_id):
    try:
        session = recording_sessions.get(device_id)
        if not session or len(session['actions']) == 0:
            return jsonify({
                'success': False,
                'error': f'没有可保存的操作记录'
            })

        # 生成Python脚本内容
        script_content = generate_script_content(device_id, session['actions'])

        # 保存脚本到文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"script_{device_id}_{timestamp}.py"
        filepath = os.path.join(app.config['SAVED_SCRIPTS_DIR'], filename)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(script_content)

        return jsonify({
            'success': True,
            'filename': filename,
            'content': script_content
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/saved_scripts')
def saved_scripts():
    try:
        # 获取已保存的脚本列表
        scripts = []
        for filename in os.listdir(app.config['SAVED_SCRIPTS_DIR']):
            if filename.endswith('.py'):
                filepath = os.path.join(app.config['SAVED_SCRIPTS_DIR'], filename)
                scripts.append({
                    'filename': filename,
                    'size': os.path.getsize(filepath),
                    'modified': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')
                })

        # 按修改时间排序（最新的在前）
        scripts.sort(key=lambda x: x['modified'], reverse=True)

        return jsonify({
            'success': True,
            'scripts': scripts
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


@app.route('/download_script/<filename>')
def download_script(filename):
    try:
        # 安全检查：只允许下载py文件
        if not filename.endswith('.py'):
            return jsonify({
                'success': False,
                'error': '不支持的文件类型'
            })

        return send_from_directory(
            app.config['SAVED_SCRIPTS_DIR'],
            filename,
            as_attachment=True,
            mimetype='text/plain'
        )
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)