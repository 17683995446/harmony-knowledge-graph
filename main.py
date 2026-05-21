"""
Harmony Knowledge Graph - 主入口
百万行级ArkTS代码知识图谱系统

使用方法:
    python main.py              # 启动Web服务
    python main.py scan <path>  # 扫描项目
    python main.py query <sql>  # 执行SQL查询
"""

import asyncio
import sys
import click
from pathlib import Path

from core.config_manager import get_configuration
from core.logger_manager import get_logger
from web.application import create_application
import uvicorn

logger = get_logger("main")


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """Harmony Knowledge Graph - 鸿蒙代码知识图谱系统"""
    # 如果没有指定子命令，默认启动Web服务
    if ctx.invoked_subcommand is None:
        ctx.invoke(serve)


@cli.command()
@click.option("--host", default="0.0.0.0", help="服务器监听地址")
@click.option("--port", default=8080, help="服务器端口")
@click.option("--reload", is_flag=True, help="启用热重载（开发模式）")
def serve(host: str, port: int, reload: bool):
    """启动Web服务"""
    config = get_configuration()
    
    logger.info(f"启动Web服务: http://{host}:{port}")
    
    app = create_application()
    
    uvicorn.run(
        app,
        host=host if host is not None else config.host,
        port=port if port is not None else config.port,
        reload=reload
    )


@cli.command()
@click.argument("project_path")
@click.option("--incremental", is_flag=True, default=True, help="增量扫描")
@click.option("--workers", default=8, help="工作进程数")
def scan(project_path: str, incremental: bool, workers: int):
    """扫描项目代码"""
    from core.pipeline_manager import PipelineManager
    
    logger.info(f"开始扫描项目: {project_path}")
    
    pipeline = PipelineManager(
        project_path=project_path,
        max_workers=workers
    )
    
    result = pipeline.run_full_pipeline(incremental=incremental)
    
    if result.success:
        logger.info("扫描完成!")
        logger.info(f"扫描文件: {result.scanned_files}")
        logger.info(f"解析实体: {result.parsed_entities}")
        logger.info(f"发现关系: {result.found_relations}")
        logger.info(f"耗时: {result.duration:.2f}秒")
    else:
        logger.error(f"扫描失败: {result.error}")
        sys.exit(1)


@cli.command()
@click.argument("sql")
def query(sql: str):
    """执行SQL查询"""
    from database.query_executor import QueryExecutor
    
    logger.info(f"执行SQL: {sql}")
    
    executor = QueryExecutor()
    result = executor.execute(sql)
    
    if result.success:
        print(f"\n查询结果 ({result.row_count} 行, {result.execution_time_ms:.2f}ms):\n")
        
        if result.data:
            # 打印表头
            headers = result.columns
            print(" | ".join(headers))
            print("-" * (sum(len(h) for h in headers) + 3 * len(headers)))
            
            # 打印数据
            for row in result.data[:20]:  # 最多显示20行
                values = [str(row.get(col, "")) for col in headers]
                print(" | ".join(values))
            
            if len(result.data) > 20:
                print(f"\n... 还有 {len(result.data) - 20} 行")
    else:
        logger.error(f"查询失败: {result.error_message}")
        sys.exit(1)


@cli.command()
def init():
    """初始化数据库"""
    from database.schema_manager import SchemaManager
    from core.config_manager import get_configuration
    
    config = get_configuration()
    
    logger.info(f"初始化数据库: {config.database_path}")
    
    schema_manager = SchemaManager(config.database_path)
    schema_manager.initialize_database()
    
    logger.info("数据库初始化完成")


@cli.command()
def stats():
    """显示统计信息"""
    from database.query_executor import QueryExecutor
    from database.schema_manager import SchemaManager
    from core.config_manager import get_configuration
    
    config = get_configuration()
    
    print("\n" + "=" * 50)
    print("Harmony Knowledge Graph - 统计信息")
    print("=" * 50 + "\n")
    
    # 数据库统计
    schema_manager = SchemaManager(config.database_path)
    table_stats = schema_manager.get_table_stats()
    
    print("数据库表统计:")
    for table, count in table_stats.items():
        print(f"  {table:30s}: {count:>8,} 行")
    
    # 项目统计
    executor = QueryExecutor()
    result = executor.get_project_statistics()
    
    if result.success and result.data:
        stats = result.data[0]
        print("\n项目统计:")
        print(f"  文件总数: {stats.get('total_files', 0):,}")
        print(f"  实体总数: {stats.get('total_entities', 0):,}")
        print(f"  调用关系: {stats.get('total_calls', 0):,}")
        print(f"  继承关系: {stats.get('total_inheritance', 0):,}")
    
    print("\n" + "=" * 50 + "\n")


@cli.command()
def reset():
    """重置数据库"""
    from database.schema_manager import SchemaManager
    from core.config_manager import get_configuration
    
    config = get_configuration()
    
    click.confirm(
        f"确定要重置数据库吗？这将删除所有数据: {config.database_path}",
        abort=True
    )
    
    logger.info("重置数据库...")
    
    schema_manager = SchemaManager(config.database_path)
    schema_manager.reset_database()
    
    logger.info("数据库重置完成")


@cli.command()
@click.argument("question")
def ask(question: str):
    """自然语言查询"""
    asyncio.run(_ask_async(question))


async def _ask_async(question: str):
    """异步执行自然语言查询"""
    from llm.sql_generator import SQLGenerator
    from llm.silicon_flow_client import SiliconFlowClient
    from database.query_executor import QueryExecutor
    
    logger.info(f"自然语言查询: {question}")
    
    async with SiliconFlowClient() as llm_client:
        generator = SQLGenerator(llm_client=llm_client)
        
        # 生成SQL
        sql_result = await generator.generate_sql(question)
        
        if not sql_result["success"]:
            logger.error(f"SQL生成失败: {sql_result.get('error')}")
            return
        
        sql = sql_result["sql"]
        print(f"\n生成的SQL:\n{sql}\n")
        
        # 执行SQL
        executor = QueryExecutor()
        query_result = executor.execute(sql)
        
        if query_result.success:
            print(f"查询结果 ({query_result.row_count} 行):\n")
            
            if query_result.data:
                headers = query_result.columns
                print(" | ".join(headers))
                print("-" * (sum(len(h) for h in headers) + 3 * len(headers)))
                
                for row in query_result.data[:20]:
                    values = [str(row.get(col, "")) for col in headers]
                    print(" | ".join(values))
        else:
            logger.error(f"查询失败: {query_result.error_message}")


if __name__ == "__main__":
    cli()
