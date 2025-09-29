import os
import base64
import time
import json
from datetime import datetime
from flask import Flask, render_template, jsonify, request
import uiautomator2 as u2
from PIL import Image
import io

app = Flask(__name__)
app.config['SAVED_SCRIPTS_DIR'] = 'saved_scripts'
app.config['RECORDING_THRESHOLD'] = 5  # 滑动识别阈值（像素）
app.config['MIN_DELAY'] = 0.1  # 最小操作间隔（秒）

# 确保保存脚本的目录存在
os.makedirs(app.config['SAVED_SCRIPTS_DIR'], exist_ok=True)

# 存储设备连接和录制状态
device_connections = {}  # 设备连接对象 {device_id: device_obj}
recording_sessions = {}  # 录制会话 {device_id: {actions: [], start_time: float, last_action_time: float}}


def get_device_list():
    """获取已连接的设备列表（优化版）"""
    try:
        from uiautomator2 import adbutils
        devices = adbutils.adb.device_list()
        return [d.serial for d in devices]
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

        # 连接设备并初始化
        d = u2.connect(device_id)
        d.wait_ready(timeout=10.0)  # 等待设备就绪
        device_connections[device_id] = d

        # 初始化录制会话（新增last_action_time记录）
        recording_sessions[device_id] = {
            'actions': [],
            'start_time': None,
            'last_action_time': 0
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

        # 压缩图片减少传输量
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=80)  # 降低质量至80%
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

        # 初始化录制会话（重置状态）
        recording_sessions[device_id] = {
            'actions': [],
            'start_time': time.time(),
            'last_action_time': 0  # 记录上一次操作时间
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

        if device_id not in recording_sessions or recording_sessions[device_id]['start_time'] is None:
            return jsonify({
                'success': False,
                'error': f'设备 {device_id} 未在录制中'
            })

        # 保留操作记录，仅标记结束
        recording_sessions[device_id]['start_time'] = None

        return jsonify({
            'success': True,
            'message': f'已停止录制设备 {device_id} 的操作，共记录 {len(recording_sessions[device_id]["actions"])} 个操作'
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
        relative_time = current_time - session['start_time']

        # 过滤过于密集的操作（避免误触）
        if relative_time - session['last_action_time'] < app.config['MIN_DELAY']:
            return jsonify({
                'success': False,
                'error': '操作过于密集，已忽略'
            })

        # 记录相对时间和操作详情
        action['time'] = relative_time
        session['actions'].append(action)
        session['last_action_time'] = relative_time  # 更新最后操作时间

        # 在设备上执行操作（给用户反馈）
        d = device_connections[device_id]
        if action['type'] == 'click':
            d.click(action['x'], action['y'])
        elif action['type'] == 'swipe':
            # 滑动添加持续时间参数（更接近真实操作）
            d.swipe(action['x1'], action['y1'], action['x2'], action['y2'], duration=0.5)

        return jsonify({
            'success': True,
            'message': f'操作已记录（共 {len(session["actions"])} 个）'
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
                'error': '没有可保存的操作记录'
            })

        # 生成Python脚本内容（优化版）
        script_lines = [
            'import uiautomator2 as u2',
            'import time',
            'import logging',
            '',
            '# 配置日志输出',
            'logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")',
            'logger = logging.getLogger(__name__)',
            '',
            f"d = u2.connect('{device_id}')",
            "d.wait_ready(timeout=10.0)",
            "logger.info('设备连接成功，开始执行脚本')",
            ""
        ]

        # 添加操作（优化时间计算）
        prev_time = 0
        for i, action in enumerate(session['actions']):
            # 添加延迟（相对于上一个操作）
            delay = action['time'] - prev_time
            if delay > app.config['MIN_DELAY']:  # 只添加明显的延迟
                script_lines.append(f"time.sleep({delay:.2f})")
                script_lines.append(f"logger.info('等待 {delay:.2f} 秒')")

            # 添加操作代码和日志
            if action['type'] == 'click':
                script_lines.append(f"d.click({action['x']}, {action['y']})")
                script_lines.append(f"logger.info('点击坐标: ({action['x']}, {action['y']})')")
            elif action['type'] == 'swipe':
                script_lines.append(f"d.swipe({action['x1']}, {action['y1']}, {action['x2']}, {action['y2']}, duration=0.5)")
                script_lines.append(f"logger.info('滑动坐标: ({action['x1']},{action['y1']}) -> ({action['x2']},{action['y2']})')")

            prev_time = action['time']

        script_lines.append("")
        script_lines.append("logger.info('脚本执行完成')")
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
            'content': script_content,
            'action_count': len(session['actions'])  # 返回操作数量
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        })


# 其他接口（saved_scripts/download_script）保持不变

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)