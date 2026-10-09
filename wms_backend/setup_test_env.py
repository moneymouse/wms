#!/usr/bin/env python3
"""
测试环境安装脚本
用于自动设置WMS后端的测试环境
"""

import subprocess
import sys
import os
from pathlib import Path


def run_command_safe(command, description):
    """安全地运行命令"""
    print(f"\n🔍 {description}")
    print(f"命令: {command}")

    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)

        if result.stdout:
            print(result.stdout)

        if result.stderr:
            print("错误输出:", result.stderr)

        if result.returncode != 0:
            print(f"❌ 命令失败，退出码: {result.returncode}")
            return False

        print(f"✅ {description} 完成")
        return True

    except Exception as e:
        print(f"❌ 执行命令时出错: {e}")
        return False


def check_python_version():
    """检查Python版本"""
    print("🐍 检查Python版本...")

    if sys.version_info < (3, 8):
        print(f"❌ Python版本过低: {sys.version}")
        print("请使用Python 3.8或更高版本")
        return False

    print(f"✅ Python版本: {sys.version}")
    return True


def install_pip_if_needed():
    """检查并安装pip"""
    try:
        import pip
        print("✅ pip 已安装")
        return True
    except ImportError:
        print("⚠️  pip 未安装，尝试安装...")
        return run_command_safe("python3 -m ensurepip", "安装pip")


def install_virtualenv():
    """安装virtualenv"""
    return run_command_safe("pip3 install virtualenv", "安装virtualenv")


def create_virtual_environment():
    """创建虚拟环境"""
    if Path("venv").exists():
        print("✅ 虚拟环境已存在")
        return True

    return run_command_safe("python3 -m venv venv", "创建虚拟环境")


def install_test_dependencies():
    """安装测试依赖"""
    # 检查是否在虚拟环境中或确保使用虚拟环境的pip
    venv_pip = None

    if Path("venv/bin/pip").exists():
        venv_pip = "./venv/bin/pip"
    elif Path("venv/Scripts/pip.exe").exists():
        venv_pip = "./venv/Scripts/pip.exe"

    if venv_pip:
        command = f"{venv_pip} install -r requirements-test.txt"
    else:
        command = "pip3 install -r requirements-test.txt"

    return run_command_safe(command, "安装测试依赖")


def verify_installation():
    """验证安装"""
    print("\n🔍 验证安装...")

    # 检查虚拟环境是否正确
    venv_python = None

    if Path("venv/bin/python").exists():
        venv_python = "./venv/bin/python"
    elif Path("venv/Scripts/python.exe").exists():
        venv_python = "./venv/Scripts/python.exe"

    if venv_python:
        command = f"{venv_python} -c 'import pytest; print(f\"pytest version: {{pytest.__version__}}\")'"
        return run_command_safe(command, "验证pytest安装")
    else:
        print("⚠️  无法找到虚拟环境的Python，使用系统Python验证")
        return run_command_safe("python3 -c 'import pytest; print(f\"pytest version: {pytest.__version__}\")'", "验证pytest安装")


def main():
    """主函数"""
    print("🚀 WMS测试环境安装器")
    print("=" * 50)

    # 切换到项目根目录
    project_root = Path(__file__).parent
    os.chdir(project_root)

    steps = [
        ("检查Python版本", check_python_version),
        ("检查pip", install_pip_if_needed),
        ("创建虚拟环境", create_virtual_environment),
        ("安装测试依赖", install_test_dependencies),
        ("验证安装", verify_installation),
    ]

    success = True
    for description, func in steps:
        if not func():
            print(f"❌ 步骤失败: {description}")
            success = False
            break

    print("\n" + "=" * 60)
    if success:
        print("🎉 测试环境安装完成！")
        print("\n下一步:")
        print("  1. 激活虚拟环境:")
        if os.name == 'nt':
            print("     .\\venv\\Scripts\\activate")
        else:
            print("     source venv/bin/activate")
        print("  2. 运行测试:")
        print("     python run_tests.py unit")
    else:
        print("❌ 安装过程中出现错误，请检查上面的错误信息并手动解决")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())