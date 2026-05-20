#!/bin/bash

# Harmony Knowledge Graph - 部署脚本
# 支持Docker部署和直接部署

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

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

# 显示帮助
show_help() {
    cat << EOF
Harmony Knowledge Graph 部署脚本

用法: ./deploy.sh [选项] [命令]

命令:
    docker          使用Docker部署
    docker-compose  使用Docker Compose部署
    local           本地部署
    update          更新部署
    stop            停止服务
    logs            查看日志
    status          查看状态

选项:
    -h, --help      显示帮助信息
    -v, --version   显示版本信息

示例:
    ./deploy.sh docker              # Docker部署
    ./deploy.sh docker-compose      # Docker Compose部署
    ./deploy.sh local               # 本地部署
    ./deploy.sh update              # 更新
    ./deploy.sh stop                # 停止服务
EOF
}

# Docker部署
deploy_docker() {
    print_info "使用Docker部署..."
    
    # 检查Docker
    if ! command -v docker &> /dev/null; then
        print_error "Docker未安装，请先安装Docker"
        exit 1
    fi
    
    # 构建镜像
    print_info "构建Docker镜像..."
    docker build -t harmony-knowledge-graph:latest .
    
    # 停止旧容器
    if docker ps -a | grep -q harmony-kg; then
        print_info "停止旧容器..."
        docker stop harmony-kg || true
        docker rm harmony-kg || true
    fi
    
    # 启动新容器
    print_info "启动容器..."
    docker run -d \
        --name harmony-kg \
        -p 8080:8080 \
        -v "$(pwd)/data:/app/data" \
        -v "$(pwd)/cache:/app/cache" \
        -v "$(pwd)/logs:/app/logs" \
        -e SILICON_FLOW_API_KEY="${SILICON_FLOW_API_KEY:-sk-uqelhavcdhfxjzjesdenxpbtqombamjniazzjtbssmdcwdvg}" \
        harmony-knowledge-graph:latest
    
    print_success "Docker部署完成!"
    print_info "访问地址: http://localhost:8080"
}

# Docker Compose部署
deploy_docker_compose() {
    print_info "使用Docker Compose部署..."
    
    # 检查Docker Compose
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose未安装，请先安装Docker Compose"
        exit 1
    fi
    
    # 启动服务
    docker-compose up -d --build
    
    print_success "Docker Compose部署完成!"
    print_info "访问地址: http://localhost:8080"
}

# 本地部署
deploy_local() {
    print_info "本地部署..."
    
    # 检查Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python3未安装"
        exit 1
    fi
    
    # 检查虚拟环境
    if [ ! -d "venv" ]; then
        print_info "创建虚拟环境..."
        python3 -m venv venv
    fi
    
    # 激活虚拟环境
    source venv/bin/activate
    
    # 安装依赖
    print_info "安装依赖..."
    pip install -r requirements.txt
    
    # 初始化数据库
    print_info "初始化数据库..."
    python main.py init
    
    # 启动服务
    print_info "启动服务..."
    print_info "访问地址: http://localhost:8080"
    python main.py serve
}

# 更新部署
update_deployment() {
    print_info "更新部署..."
    
    # 拉取最新代码
    if [ -d ".git" ]; then
        git pull
    fi
    
    # 检查是否有Docker容器在运行
    if docker ps | grep -q harmony-kg; then
        print_info "更新Docker部署..."
        docker-compose down
        docker-compose up -d --build
    elif [ -d "venv" ]; then
        print_info "更新本地部署..."
        source venv/bin/activate
        pip install -r requirements.txt
        print_info "更新完成，请手动重启服务"
    else
        print_warning "未检测到现有部署"
    fi
    
    print_success "更新完成!"
}

# 停止服务
stop_service() {
    print_info "停止服务..."
    
    # 停止Docker容器
    if docker ps | grep -q harmony-kg; then
        docker stop harmony-kg
        print_success "Docker容器已停止"
    fi
    
    # 停止Docker Compose
    if [ -f "docker-compose.yml" ]; then
        docker-compose down
        print_success "Docker Compose服务已停止"
    fi
    
    print_success "服务已停止"
}

# 查看日志
show_logs() {
    print_info "查看日志..."
    
    if docker ps | grep -q harmony-kg; then
        docker logs -f harmony-kg
    elif [ -f "docker-compose.yml" ]; then
        docker-compose logs -f
    else
        if [ -f "logs/harmony_kg_$(date +%Y%m%d).log" ]; then
            tail -f "logs/harmony_kg_$(date +%Y%m%d).log"
        else
            print_warning "未找到日志文件"
        fi
    fi
}

# 查看状态
show_status() {
    print_info "查看服务状态..."
    
    # Docker状态
    if docker ps | grep -q harmony-kg; then
        print_success "Docker容器运行中"
        docker ps | grep harmony-kg
    else
        print_warning "Docker容器未运行"
    fi
    
    # 端口检查
    if netstat -tuln 2>/dev/null | grep -q ':8080'; then
        print_success "端口8080正在监听"
    elif ss -tuln 2>/dev/null | grep -q ':8080'; then
        print_success "端口8080正在监听"
    else
        print_warning "端口8080未监听"
    fi
}

# 主函数
main() {
    case "${1:-}" in
        docker)
            deploy_docker
            ;;
        docker-compose)
            deploy_docker_compose
            ;;
        local)
            deploy_local
            ;;
        update)
            update_deployment
            ;;
        stop)
            stop_service
            ;;
        logs)
            show_logs
            ;;
        status)
            show_status
            ;;
        -h|--help)
            show_help
            ;;
        -v|--version)
            echo "Harmony Knowledge Graph v1.0.0"
            ;;
        *)
            show_help
            exit 1
            ;;
    esac
}

main "$@"
