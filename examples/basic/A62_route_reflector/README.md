# Route Reflector on Mini Internet

这个例子基于 `examples/internet/B00_mini_internet/mini_internet.py` 的拓扑扩展 Route Reflector (RR) 配置。它保留 B00 的 IX、transit AS、stub AS 和 eBGP peering 结构，然后在不同 AS 内展示三种 iBGP 模式：

- `AS2`: 不设置 RR，继续使用原来的 full-mesh iBGP。
- `AS12`: 一个 cluster，一个 RR，展示单 RR 模式。
- `AS3`: 两个 cluster，每个 cluster 一个 RR，展示多 RR 模式和 RR 之间的 mesh。

## File Roles

- `route_reflector.py`: 用户输入脚本。创建 mini Internet 拓扑，给指定 AS 添加 RR metadata，并生成 Docker Compose 输出。
- `README.md`: 示例说明。解释拓扑、RR 配置方式、运行命令和验证命令。
- `codex_worklog.md`: 变更记录。记录示例创建和验证过程。
- `output/`: 生成输出。运行脚本后由 Docker compiler 覆盖生成，不需要手工编辑。

## Run

建议使用 `seedpy310` conda 环境，从本目录运行：

```bash
cd /home/lxl/seed-emulator/examples/basic/A62_route_reflector
PYTHONPATH=/home/lxl/seed-emulator conda run -n seedpy310 python route_reflector.py amd
```

脚本会生成 `output/`。如果需要部署：

```bash
cd /home/lxl/seed-emulator/examples/basic/A62_route_reflector/output
DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build
docker compose up -d
docker compose ps
```

当前 Docker Compose/BuildKit 在这个项目的生成镜像上可能会先解析本地哈希镜像名并尝试从 Docker Hub 拉取，导致普通 `docker compose build` 失败。因此推荐使用上面的传统 builder 命令。

停止并清理容器：

```bash
cd /home/lxl/seed-emulator/examples/basic/A62_route_reflector/output
docker compose down
```

## Base Topology

示例沿用 B00 的 mini Internet 结构：

- IX: `100` 到 `105`。
- Tier 1 transit AS: `AS2`、`AS3`、`AS4`。
- Tier 2 transit AS: `AS11`、`AS12`。
- Stub AS: `AS150`、`AS151`、`AS152`、`AS153`、`AS154`、`AS160`、`AS161`、`AS162`、`AS163`、`AS164`、`AS170`、`AS171`。

这些 AS 的 eBGP peering 和 B00 保持一致。RR 配置只影响 AS 内部 iBGP session 的生成方式，不改变 AS 间 eBGP 关系。

## Full-Mesh Example

`AS2` 不调用任何 RR API：

```python
# AS2 keeps the B00 behavior and is rendered by Ibgp as legacy full mesh.
```

`Ibgp.render()` 在聚合 cluster 时会看到 `AS2` 只有默认 cluster 且没有 RR，于是进入 `_render_full_mesh_mode()`。因此 `AS2` 内的 `r100`、`r101`、`r102`、`r105` 会按原逻辑建立 full-mesh iBGP。

部署后可以检查：

```bash
docker compose exec brdnode_2_r100 birdc show protocols
```

## One-RR Example

`AS12` 有两个 router：`r101` 和 `r104`。示例注册一个 cluster，并把 `r101` 设置为 RR，`r104` 设置为 client：

```python
AS12_CLUSTER_ID = "10.12.0.1"

as12 = base.getAutonomousSystem(12)
as12.createCluster(AS12_CLUSTER_ID)

as12.getRouter('r101') \
    .joinBgpCluster(AS12_CLUSTER_ID) \
    .makeRouteReflector()

as12.getRouter('r104') \
    .joinBgpCluster(AS12_CLUSTER_ID)
```

渲染结果：

- `r101` 使用 `ibgp_rr_server` 模板，对 `r104` 开启 `rr client` 和 `rr cluster id 10.12.0.1`。
- `r104` 使用 `ibgp_client` 模板连接到 `r101`。

部署后可以检查：

```bash
docker compose exec brdnode_12_r101 birdc show protocols
docker compose exec brdnode_12_r101 grep -n "rr cluster id" /etc/bird/bird.conf
```

## Two-RR Example

`AS3` 有四个 router：`r100`、`r103`、`r104`、`r105`。示例创建两个 cluster：

- `10.3.0.1`: `r100` 是 RR，`r105` 是 client。
- `10.3.0.2`: `r103` 是 RR，`r104` 是 client。

配置代码：

```python
AS3_WEST_CLUSTER_ID = "10.3.0.1"
AS3_EAST_CLUSTER_ID = "10.3.0.2"

as3 = base.getAutonomousSystem(3)
as3.createCluster(AS3_WEST_CLUSTER_ID)
as3.createCluster(AS3_EAST_CLUSTER_ID)

as3.getRouter('r100') \
    .joinBgpCluster(AS3_WEST_CLUSTER_ID) \
    .makeRouteReflector()

as3.getRouter('r105') \
    .joinBgpCluster(AS3_WEST_CLUSTER_ID)

as3.getRouter('r103') \
    .joinBgpCluster(AS3_EAST_CLUSTER_ID) \
    .makeRouteReflector()

as3.getRouter('r104') \
    .joinBgpCluster(AS3_EAST_CLUSTER_ID)
```

渲染结果：

- cluster 内部建立 RR-client session。
- `r100` 和 `r103` 作为所有 RR 集合的一部分，被 `_render_rr_mode()` 自动建立普通 iBGP mesh。

部署后可以检查：

```bash
docker compose exec brdnode_3_r100 birdc show protocols
docker compose exec brdnode_3_r103 birdc show protocols
docker compose exec brdnode_3_r100 grep -n "Ibgp_mesh" /etc/bird/bird.conf
```

## API Rules

使用 RR 时需要遵守这些规则：

- 先在 AS 上调用 `createCluster(cluster_id)` 注册 cluster。
- 再在 router 上调用 `joinBgpCluster(cluster_id)` 加入 cluster。
- RR router 额外调用 `makeRouteReflector()`。
- 在一个启用 RR 的 AS 中，每个 cluster 必须至少有一个 RR 和一个 client。
- 如果 AS 里有多个 cluster，所有 router 都应显式加入某个 cluster，避免被放入默认 cluster 后触发校验失败。
- 如果 AS 没有任何 RR，并且只有默认 cluster，`Ibgp` 会保持原 full-mesh 行为。

## Validation

编译前先做语法检查：

```bash
cd /home/lxl/seed-emulator
conda run -n seedpy310 python -m py_compile examples/basic/A62_route_reflector/route_reflector.py
```

生成输出：

```bash
cd /home/lxl/seed-emulator/examples/basic/A62_route_reflector
PYTHONPATH=/home/lxl/seed-emulator conda run -n seedpy310 python route_reflector.py amd
```

不部署也可以直接检查生成的 BIRD 配置：

```bash
rg -n "rr client|rr cluster id|Ibgp_mesh|protocol bgp Ibgp" output/brdnode_2_r100 output/brdnode_3_r100 output/brdnode_3_r103 output/brdnode_12_r101
```

部署后建议以控制面为主验证：

```bash
docker compose exec brdnode_12_r101 birdc show protocols
docker compose exec brdnode_3_r100 birdc show protocols
docker compose exec brdnode_3_r103 birdc show protocols
```

当前 BGP 模板默认包含 `disabled;`，本例不会在启动脚本里自动执行 `birdc enable all`。如果部署后要让 session 真正建立，可以进入对应 router 容器手动执行：

```bash
docker compose exec brdnode_12_r101 birdc enable all
docker compose exec brdnode_3_r100 birdc enable all
docker compose exec brdnode_3_r103 birdc enable all
```

如果当前路由模板仍然限制 BGP route 写入 Linux kernel，跨 AS `ping` 或 `curl` 可能不能代表 RR 控制面是否正确。这个例子重点验证的是 BIRD 配置和 iBGP session 生成方式。
