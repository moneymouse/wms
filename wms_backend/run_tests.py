#!/usr/bin/env python3
"""
测试运行脚本
用于运行WMS后端的所有测试
"""

import sys
import subprocess
import os
from pathlib import Path
import shutil


def find_python_executable():
    """查找最合适的Python解释器"""
    # 首先检查是否在conda环境中
    conda_env = os.getenv('CONDA_DEFAULT_ENV')
    if conda_env and conda_env != 'base':
        # 在conda环境中，使用当前的Python解释器
        return sys.executable

    # 检查是否在虚拟环境中
    venv_path = os.getenv('VIRTUAL_ENV')
    if venv_path:
        if os.name == 'nt':  # Windows
            python_exe = Path(venv_path) / "Scripts" / "python.exe"
        else:  # Unix/Linux/macOS
            python_exe = Path(venv_path) / "bin" / "python"

        if python_exe.exists():
            return str(python_exe)

    # 尝试找到项目中的虚拟环境
    project_root = Path(__file__).parent
    possible_venv_paths = [
        project_root / "venv",
        project_root / "env",
        project_root / ".venv",
        project_root / "virtualenv"
    ]

    for venv_path in possible_venv_paths:
        if venv_path.exists():
            if os.name == 'nt':  # Windows
                python_exe = venv_path / "Scripts" / "python.exe"
            else:  # Unix/Linux/macOS
                python_exe = venv_path / "bin" / "python"

            if python_exe.exists():
                return str(python_exe)

    # 最后使用系统Python
    python_candidates = ['python3', 'python']
    for candidate in python_candidates:
        if shutil.which(candidate):
            return candidate

    return sys.executable


def run_command(command, description, use_venv_python=True):
    """运行命令并处理输出"""
    print(f"\n{'='*60}")
    print(f"🔍 {description}")
    print(f"{'='*60}")

    try:
        # 如果启用虚拟环境Python且命令包含pytest，尝试使用当前环境的Python
        if use_venv_python and command.startswith('pytest'):
            # 检查是否在conda环境中
            conda_env = os.getenv('CONDA_DEFAULT_ENV')
            if conda_env and conda_env != 'base':
                # 在conda环境中，直接使用pytest（应该已经安装在conda环境中）
                print(f"💡 使用conda环境 ({conda_env}) 中的pytest")
            else:
                # 尝试查找虚拟环境Python
                venv_python = find_python_executable()
                if venv_python:
                    command = command.replace('pytest', f"{venv_python} -m pytest")
                    print(f"💡 使用虚拟环境Python: {command}")
                else:
                    # 检查 pytest 是否可用
                    result = subprocess.run(['which', 'pytest'],
                                          capture_output=True, text=True)
                    if result.returncode != 0:
                        # 试试 python -m pytest
                        command = command.replace('pytest', 'python3 -m pytest')
                        print(f"⚠️  pytest 命令未找到，尝试使用: {command}")

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


def find_venv_python():
    """查找虚拟环境或conda环境的Python解释器"""
    # 首先检查是否在conda环境中
    conda_env = os.getenv('CONDA_DEFAULT_ENV')
    if conda_env and conda_env != 'base':
        # 在conda环境中，使用当前的Python解释器
        return sys.executable

    # 检查是否在虚拟环境中
    venv_path = os.getenv('VIRTUAL_ENV')
    if venv_path:
        if os.name == 'nt':  # Windows
            python_exe = Path(venv_path) / "Scripts" / "python.exe"
        else:  # Unix/Linux/macOS
            python_exe = Path(venv_path) / "bin" / "python"

        if python_exe.exists():
            return str(python_exe)

    # 尝试找到项目中的虚拟环境
    project_root = Path(__file__).parent
    possible_venv_paths = [
        project_root / "venv",
        project_root / "env",
        project_root / ".venv",
        project_root / "virtualenv"
    ]

    for venv_path in possible_venv_paths:
        if venv_path.exists():
            if os.name == 'nt':  # Windows
                python_exe = venv_path / "Scripts" / "python.exe"
            else:  # Unix/Linux/macOS
                python_exe = venv_path / "bin" / "python"

            if python_exe.exists():
                return str(python_exe)

    return None


def check_dependencies():
    """检查测试依赖"""
    print("📋 检查测试依赖...")

    # 检查当前环境信息
    conda_env = os.getenv('CONDA_DEFAULT_ENV')
    if conda_env:
        print(f"🐍 当前conda环境: {conda_env}")

    venv_path = os.getenv('VIRTUAL_ENV')
    if venv_path:
        print(f"🐍 当前虚拟环境: {venv_path}")

    print(f"🐍 Python版本: {sys.version}")

    # 检查pytest是否安装
    try:
        import pytest
        print(f"✅ pytest 已安装 (版本: {pytest.__version__})")
    except ImportError:
        print("❌ pytest 未安装")
        if conda_env and conda_env != 'base':
            print("请运行: conda install pytest pytest-flask pytest-mock pytest-cov")
        else:
            print("请运行: pip install -r requirements-test.txt")
        return False

    # 检查其他依赖 - 包名和导入名的映射
    required_packages = {
        "pytest-flask": "pytest_flask",
        "pytest-mock": "pytest_mock",
        "pytest-cov": "pytest_cov",
        "faker": "faker",
        "responses": "responses",
        "factory-boy": "factory",
        "freezegun": "freezegun",
        "assertpy": "assertpy",
        "pydantic": "pydantic"
    }

    missing_packages = []
    for package, import_name in required_packages.items():
        try:
            __import__(import_name)
            print(f"✅ {package} 已安装")
        except ImportError:
            missing_packages.append(package)
            print(f"❌ {package} 未安装")

    if missing_packages:
        print(f"❌ 缺少依赖: {', '.join(missing_packages)}")
        if conda_env and conda_env != 'base':
            print("请运行: conda install -c conda-forge " + " ".join(missing_packages))
        else:
            print("请运行: pip install -r requirements-test.txt")
        return False

    return True


def run_unit_tests():
    """运行单元测试"""
    # 首先检查测试目录是否存在
    if not Path("tests/unit").exists():
        print("❌ 单元测试目录 'tests/unit' 不存在")
        return False

    # 基本的单元测试命令
    commands = [
        ("pytest tests/unit/ -v --tb=short", "运行所有单元测试"),
    ]

    # 检查具体测试文件是否存在，如果存在则添加到命令列表
    test_patterns = [
        ("test_auth_*.py", "认证相关测试"),
        ("test_order_*.py", "订单相关测试"),
        ("test_cargo_*.py", "货物相关测试"),
        ("test_customer_*.py", "客户相关测试"),
        ("test_log_*.py", "日志相关测试"),
    ]

    for pattern, description in test_patterns:
        test_files = list(Path("tests/unit").glob(pattern))
        if test_files:
            file_list = " ".join(str(f) for f in test_files)
            commands.append((f"pytest {file_list} -v", f"运行{description}"))

    success = True
    for command, description in commands:
        if not run_command(command, description):
            success = False
            # 继续运行其他测试，不要一失败就停止

    return success


def run_integration_tests():
    """运行集成测试"""
    if not Path("tests/integration").exists():
        print("❌ 集成测试目录 'tests/integration' 不存在")
        return False

    command = "pytest tests/integration/ -v --tb=short"
    return run_command(command, "运行集成测试")


def run_coverage_tests():
    """运行带覆盖率的测试"""
    if not Path("tests").exists():
        print("❌ 测试目录 'tests' 不存在")
        return False

    command = "pytest tests/ --cov=. --cov-report=html --cov-report=term --tb=short"
    return run_command(command, "运行覆盖率测试")


def run_specific_marker_tests(marker):
    """运行特定标记的测试"""
    command = f"pytest -m {marker} -v --tb=short"
    return run_command(command, f"运行 {marker} 标记的测试")


def check_virtual_environment():
    """检查并设置虚拟环境或conda环境"""
    print("🔍 检查Python环境...")

    # 首先检查是否在conda环境中
    conda_env = os.getenv('CONDA_DEFAULT_ENV')
    if conda_env:
        if conda_env != 'base':
            print(f"✅ 当前在conda环境中: {conda_env}")
            return True
        else:
            print("⚠️  当前在conda base环境，建议激活WMS环境:")
            print("   conda activate WMS")

    # 检查是否在虚拟环境中
    venv_path = os.getenv('VIRTUAL_ENV')
    if venv_path:
        print(f"✅ 当前在虚拟环境中: {venv_path}")
        return True

    # 尝试找到项目中的虚拟环境
    project_root = Path(__file__).parent
    possible_venv_paths = [
        project_root / "venv",
        project_root / "env",
        project_root / ".venv",
        project_root / "virtualenv"
    ]

    for venv_path in possible_venv_paths:
        if venv_path.exists():
            print(f"🔍 找到虚拟环境: {venv_path}")

            # 设置虚拟环境的Python路径
            if os.name == 'nt':  # Windows
                python_path = venv_path / "Scripts" / "python.exe"
            else:  # Unix/Linux/macOS
                python_path = venv_path / "bin" / "python"

            if python_path.exists():
                # 更新sys.path以使用虚拟环境
                site_packages = venv_path / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
                if site_packages.exists():
                    sys.path.insert(0, str(site_packages))
                    print(f"✅ 已设置虚拟环境路径: {site_packages}")
                    return True

    print("⚠️  未检测到conda环境或虚拟环境，建议:")
    print("   方案1 (推荐): conda activate WMS")
    print("   方案2: 创建虚拟环境:")
    print("     python3 -m venv venv")
    print("     source venv/bin/activate  # or venv\\Scripts\\activate on Windows")
    print("     pip install -r requirements-test.txt")

    return False


def main():
    """主函数"""
    print("🚀 WMS后端测试运行器")
    print("=" * 50)

    # 切换到项目根目录
    project_root = Path(__file__).parent
    os.chdir(project_root)

    # 检查虚拟环境
    check_virtual_environment()

    # 检查依赖
    if not check_dependencies():
        sys.exit(1)

    # 解析命令行参数
    if len(sys.argv) < 2:
        print("\n📖 使用方法:")
        print("python run_tests.py [选项]")
        print("\n可用选项:")
        print("  all        - 运行所有测试")
        print("  unit       - 只运行单元测试")
        print("  integration - 只运行集成测试")
        print("  coverage   - 运行覆盖率测试")
        print("  auth       - 只运行认证相关测试")
        print("  order      - 只运行订单相关测试")
        print("  cargo      - 只运行货物相关测试")
        print("  customer   - 只运行客户相关测试")
        print("  log        - 只运行日志相关测试")
        print("  controller - 只运行控制器测试")
        print("  service    - 只运行服务测试")
        sys.exit(0)

    test_type = sys.argv[1].lower()
    success = True

    if test_type == "all":
        print("🧪 运行所有测试...")
        success = run_unit_tests() and run_integration_tests()

    elif test_type == "unit":
        print("🔬 运行单元测试...")
        success = run_unit_tests()

    elif test_type == "integration":
        print("🔗 运行集成测试...")
        success = run_integration_tests()

    elif test_type == "coverage":
        print("📊 运行覆盖率测试...")
        success = run_coverage_tests()

    elif test_type in [
        "auth",
        "order",
        "cargo",
        "customer",
        "log",
        "controller",
        "service",
    ]:
        print(f"🎯 运行 {test_type} 相关测试...")
        success = run_specific_marker_tests(test_type)

    else:
        print(f"❌ 未知的测试类型: {test_type}")
        sys.exit(1)

    # 输出结果
    print("\n" + "=" * 60)
    if success:
        print("🎉 所有测试都通过了！")
        sys.exit(0)
    else:
        print("❌ 有测试失败，请检查上面的错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
