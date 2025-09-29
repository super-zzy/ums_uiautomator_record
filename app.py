# app.py
import os
import base64
import time
import json
from datetime import datetime
from flask import Flask, render_template, jsonify, request
import uiautomator2 as u2
from PIL import Image
import io
# 引入工具函数
from utils import parse_element_by_coords

app = Flask(__name__)
app.config['SAVED_SCRIPTS_DIR'] = 'saved_scripts'

# 确保保存脚本的目录存在
os.makedirs(app.config['SAVED_SCRIPTS_DIR'], exist_ok=True)

# 存储设备连接和录制状态
device_connections = {}  # 设备连接对象
recording_sessions = {}  # 录制会话 {device_id: {actions: [], start_time: }}


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
def screenshot(device_id):
    try:
        if device_id not in device_connections:
            return jsonify({
                'success': False,
                'error': f'未连接到设备 {device_id}'
            })

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
def start_recording(device_id):
    try:
        if device_id not in device_connections:
            return jsonify({
                'success': False,
                'error': f'未连接到设备 {device_id}'
            })

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
def stop_recording(device_id):
    try:
        if device_id not in device_connections:
            return jsonify({
                'success': False,
                'error': f'未连接到设备 {device_id}'
            })

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
def record_action(device_id):
    try:
        if device_id not in device_connections:
            return jsonify({
                'success': False,
                'error': f'未连接到设备 {device_id}'
            })

        session = recording_sessions.get(device_id)
        if not session or session['start_time'] is None:
            return jsonify({
                'success': False,
                'error': f'设备 {device_id} 未在录制中'
            })

        action = request.json
        current_time = time.time()

        # 记录相对时间（自录制开始以来的秒数）
        action['time'] = current_time - session['start_time']

        # 获取设备对象
        d = device_connections[device_id]

        # 获取UI层次结构并解析元素信息（关键修改点）
        if action['type'] == 'click':
            # 只有点击操作需要解析元素（滑动操作仍使用坐标）
            xml = d.dump_hierarchy()
            element_info = parse_element_by_coords(xml, action['x'], action['y'])
            action['element'] = element_info

        # 将操作添加到会话
        session['actions'].append(action)

        # 在设备上执行操作（给用户反馈）
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
def save_script(device_id):
    try:
        if device_id not in device_connections:
            return jsonify({
                'success': False,
                'error': f'未连接到设备 {device_id}'
            })

        session = recording_sessions.get(device_id)
        if not session or len(session['actions']) == 0:
            return jsonify({
                'success': False,
                'error': f'没有可保存的操作记录'
            })

        # 生成Python脚本内容
        script_lines = [
            'import uiautomator2 as u2',
            'import time',
            '',
            f"d = u2.connect('{device_id}')",
            "d.wait_ready(timeout=10.0)",
            ""
        ]

        # 添加操作（关键修改点：优先使用xpath）
        prev_time = 0
        for action in session['actions']:
            # 添加延迟（相对于上一个操作）
            delay = action['time'] - prev_time
            if delay > 0.1:  # 只添加明显的延迟
                script_lines.append(f"time.sleep({delay:.2f})")

            # 添加操作代码
            if action['type'] == 'click':
                # 优先使用xpath定位
                if 'element' in action and action['element'].get('xpath'):
                    script_lines.append(f"d.xpath('{action['element']['xpath']}').click()")
                else:
                    script_lines.append(f"d.click({action['x']}, {action['y']})")
            elif action['type'] == 'swipe':
                script_lines.append(f"d.swipe({action['x1']}, {action['y1']}, {action['x2']}, {action['y2']})")

            prev_time = action['time']

        script_content = '\n'.join(script_lines)

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
        filepath = os.path.join(app.config['SAVED_SCRIPTS_DIR'], filename)

        if not os.path.exists(filepath) or not filename.endswith('.py'):
            return jsonify({
                'success': False,
                'error': '脚本文件不存在'
            })

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        return jsonify({
            'success': True,
            'filename': filename,
            'content': content
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)