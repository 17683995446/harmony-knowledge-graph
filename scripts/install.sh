#!/bin/bash

# Harmony Knowledge Graph - 安装脚本
# 百万行级ArkTS代码知识图谱系统

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 打印函数
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查命令是否存在
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# 检查Python版本
check_python() {
    print_info "检查Python环境..."
    
    if command_exists python3; then
        PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
        print_success "Python版本: $PYTHON_VERSION"
        
        # 检查版本是否>=3.9
        REQUIRED_VERSION="3.9"
        if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" = "$REQUIRED_VERSION" ]; then 
            print_success "Python版本符合要求 (>=3.9)"
        else
            print_error "Python版本过低，需要>=3.9"
            exit 1
        fi
    else
        print_error "未找到Python3，请先安装Python3.9或更高版本"
        exit 1
    fi
}

# 检查pip
check_pip() {
    print_info "检查pip..."
    
    if command_exists pip3; then
        print_success "pip3已安装"
    else
        print_warning "pip3未安装，尝试安装..."
        python3 -m ensurepip --upgrade || {
            print_error "pip安装失败，请手动安装"
            exit 1
        }
    fi
}

# 创建虚拟环境
create_venv() {
    print_info "创建虚拟环境..."
    
    if [ -d "venv" ]; then
        print_warning "虚拟环境已存在，跳过创建"
    else
        python3 -m venv venv
        print_success "虚拟环境创建完成"
    fi
}

# 安装依赖
install_dependencies() {
    print_info "安装Python依赖..."
    
    source venv/bin/activate
    
    # 升级pip
    pip install --upgrade pip
    
    # 安装依赖
    pip install -r requirements.txt
    
    print_success "依赖安装完成"
}

# 创建目录结构
create_directories() {
    print_info "创建目录结构..."
    
    mkdir -p data
    mkdir -p cache
    mkdir -p logs
    mkdir -p projects
    
    print_success "目录结构创建完成"
}

# 配置环境变量
setup_env() {
    print_info "配置环境变量..."
    
    if [ -f ".env" ]; then
        print_warning ".env文件已存在，跳过创建"
    else
        cp .env.example .env
        print_success ".env文件创建完成"
        print_warning "请编辑.env文件，配置你的硅基流动API密钥"
    fi
}

# 初始化数据库
init_database() {
    print_info "初始化数据库..."
    
    source venv/bin/activate
    python main.py init
    
    print_success "数据库初始化完成"
}

# 创建启动脚本
create_start_script() {
    print_info "创建启动脚本..."
    
    cat > start.sh << 'EOF'
#!/bin/bash

# Harmony Knowledge Graph 启动脚本

set -e

# 激活虚拟环境
source venv/bin/activate

# 启动服务
echo "启动 Harmony Knowledge Graph..."
echo "访问地址: http://localhost:8080"
python main.py serve "$@"
EOF

    chmod +x start.sh
    print_success "启动脚本创建完成: ./start.sh"
}

# 显示使用说明
show_usage() {
    echo ""
    echo "========================================"
    echo "  Harmony Knowledge Graph 安装完成!"
    echo "========================================"
    echo ""
    echo "使用说明:"
    echo ""
    echo "1. 启动Web服务:"
    echo "   ./start.sh"
    echo ""
    echo "2. 扫描项目:"
    echo "   python main.py scan /path/to/your/project"
    echo ""
    echo "3. 自然语言查询:"
    echo "   python main.py ask '查找所有使用了@Entry装饰器的类'"
    echo ""
    echo "4. 执行SQL查询:"
    echo "   python main.py query 'SELECT * FROM entities LIMIT 10'"
    echo ""
    echo "5. 查看统计:"
    echo "   python main.py stats"
    echo ""
    echo "Web界面访问:"
    echo "   http://localhost:8080"
    echo ""
    echo "========================================"
}

# 主函数
main() {
    echo "========================================"
    echo "  Harmony Knowledge Graph 安装程序"
    echo "========================================"
    echo ""
    
    # 检查是否在项目根目录
    if [ ! -f "requirements.txt" ]; then
        print_error "请在项目根目录运行此脚本"
        exit 1
    fi
    
    # 执行安装步骤
    check_python
    check_pip
    create_venv
    install_dependencies
    create_directories
    setup_env
    init_database
    create_start_script
    
    # 显示使用说明
    show_usage
}

# 运行主函数
main "$@"
