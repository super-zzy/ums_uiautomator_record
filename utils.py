# utils.py
import xml.etree.ElementTree as ET
from typing import Dict, Optional


def parse_element_by_coords(xml: str, x: int, y: int) -> Dict[str, Optional[str]]:
    """
    从UI层次结构XML中解析指定坐标(x,y)对应的元素属性

    Args:
        xml: 从uiautomator2获取的UI层次结构XML字符串
        x: 设备上的X坐标
        y: 设备上的Y坐标

    Returns:
        包含元素属性的字典，包括xpath、resource_id、text、class_name等
    """
    result = {
        'xpath': None,
        'resource_id': None,
        'text': None,
        'class_name': None,
        'package': None,
        'content_desc': None
    }

    try:
        # 解析XML
        root = ET.fromstring(xml)

        # 递归查找包含目标坐标的元素
        target_element = find_element_by_coords(root, x, y)
        if not target_element:
            return result

        # 提取元素属性
        result['resource_id'] = target_element.get('resource-id')
        result['text'] = target_element.get('text')
        result['class_name'] = target_element.get('class')
        result['package'] = target_element.get('package')
        result['content_desc'] = target_element.get('content-desc')

        # 生成XPath
        result['xpath'] = generate_xpath(target_element)

    except Exception as e:
        print(f"解析元素失败: {str(e)}")

    return result


def find_element_by_coords(element: ET.Element, x: int, y: int) -> Optional[ET.Element]:
    """递归查找包含指定坐标的元素"""
    # 获取元素边界
    bounds = element.get('bounds')
    if not bounds:
        return None

    # 解析边界坐标 (格式: [x1,y1][x2,y2])
    try:
        bounds = bounds.replace('[', '').replace(']', '')
        x1, y1, x2, y2 = map(int, bounds.split(','))

        # 检查坐标是否在当前元素范围内
        if x1 <= x <= x2 and y1 <= y <= y2:
            # 优先检查子元素，找到最内层的元素
            for child in element:
                child_result = find_element_by_coords(child, x, y)
                if child_result:
                    return child_result
            # 如果没有子元素包含该坐标，则返回当前元素
            return element
    except (ValueError, IndexError):
        pass

    return None


def generate_xpath(element: ET.Element) -> str:
    """为元素生成唯一XPath"""
    xpath_parts = []
    current = element

    while current is not None:
        # 获取当前元素的标签名
        tag = current.tag

        # 查找当前元素在父元素中的位置
        parent = current.getparent()
        if parent is None:
            xpath_parts.insert(0, tag)
            break

        # 计算同级别同标签元素的索引
        siblings = [s for s in parent if s.tag == tag]
        if len(siblings) > 1:
            index = siblings.index(current) + 1  # XPath索引从1开始
            xpath_parts.insert(0, f"{tag}[{index}]")
        else:
            xpath_parts.insert(0, tag)

        current = parent

    return '/' + '/'.join(xpath_parts)