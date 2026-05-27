# Route Reflector iBGP

这个例子展示如何在一个 AS 内使用 Route Reflector (RR) 代替原来的全互联 iBGP。拓扑中的 `AS62` 是 transit AS，连接 `AS150` 和 `AS151` 两个 stub AS。`AS62` 内部被拆成两个 iBGP cluster：

- `10.62.0.1`: west cluster，`rr_west` 是 RR，`edge100` 和 `core_west` 是 client。
- `10.62.0.2`: east cluster，`rr_east` 是 RR，`edge101` 和 `core_east` 是 client。

`Ibgp` layer 在渲染时会发现 `AS62` 存在 RR，因此进入 RR 模式：cluster 内部只建立 client 到 RR 的 iBGP session，所有 RR 之间再建立普通 full-mesh iBGP session。

## Run

建议在仓库根目录或本目录下使用 `seedpy310` conda 环境运行。脚本会在本目录生成 `output/`：

```bash
cd /home/lxl/seed-emulator/examples/basic/A62_route_reflector
PYTHONPATH=/home/lxl/seed-emulator conda run -n seedpy310 python route_reflector.py amd
cd output
DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build
docker compose up -d
docker compose ps
```

如果当前 Docker Compose/BuildKit 可以正确处理本地中间镜像，也可以直接运行 `docker compose build`。本环境中 BuildKit 会先解析本地哈希镜像名并尝试从 Docker Hub 拉取，所以推荐使用上面的传统 builder 命令。

```bash
DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose build
```

启动后可以查看 RR 节点上的 BIRD 协议状态：

```bash
docker compose exec rnode_62_rr_west birdc show protocols
docker compose exec rnode_62_rr_east birdc show protocols
docker compose exec brdnode_62_edge100 birdc show route table t_bgp
docker compose exec brdnode_62_edge101 birdc show route table t_bgp
```

因为当前路由模板中的 kernel export filter 不把 BGP 路由写入 Linux kernel，跨 AS `curl`/`ping` 不是这个例子的主要验证方式。这个例子重点验证 RR 控制面：RR-client session、RR-RR mesh session 是否 Established，以及对端 AS 前缀是否出现在 `t_bgp` 中。

停止并清理运行中的容器：

```bash
cd /home/lxl/seed-emulator/examples/basic/A62_route_reflector/output
docker compose down
```

## Create Layers

这个例子使用以下 layers：

- `Base`: 创建 AS、IX、router、host 和本地网络。
- `Routing`: 给节点安装基础路由能力。
- `Ebgp`: 建立 AS 之间的 eBGP peering。
- `Ibgp`: 根据 router 上的 RR/cluster 配置渲染 AS 内 iBGP。
- `Ospf`: 给 AS 内部网络建立 IGP 可达性，让 iBGP loopback neighbor 可以互通。
- `WebService`: 在两个 stub AS 的 host 上安装简单 Web 服务，便于后续验证跨 AS 连通性。

## Create Clusters

RR cluster 先在 `AutonomousSystem` 上注册：

```python
WEST_CLUSTER_ID = "10.62.0.1"
EAST_CLUSTER_ID = "10.62.0.2"

as62 = base.createAutonomousSystem(62)
as62.createCluster(WEST_CLUSTER_ID)
as62.createCluster(EAST_CLUSTER_ID)
```

`createCluster()` 只是注册 cluster ID。真正的成员关系来自 router 上的 `joinBgpCluster()` 和 `makeRouteReflector()`。

Cluster ID 会被写入 BIRD 配置中的 `rr cluster id`，所以建议使用 IPv4 地址形式的字符串，并且同一个 AS 内保持唯一。

## Add RR and Clients

普通 client router 只需要加入 cluster：

```python
as62.createRouter('edge100') \
    .joinNetwork('ix100') \
    .joinNetwork('net_west') \
    .joinBgpCluster(WEST_CLUSTER_ID)
```

RR router 需要先加入 cluster，然后标记为 RR：

```python
as62.createRouter('rr_west') \
    .joinNetwork('net_west') \
    .joinNetwork('net_core') \
    .joinBgpCluster(WEST_CLUSTER_ID) \
    .makeRouteReflector()
```

`makeRouteReflector()` 默认参数是 `True`，也可以显式传入 `False` 取消 RR 标记：

```python
router.makeRouteReflector(False)
```

## Validation Rules

当前 RR 聚合逻辑在 `Ibgp.render()` 中调用 `AutonomousSystem._aggregateBgpClusters()`，它会从 AS 内所有 router 读取：

- `getBgpClusterId()`
- `isRouteReflector()`

然后合并出 `cluster_id -> (rr_set, client_set)`。

需要注意这些规则：

- `joinBgpCluster(cluster_id)` 使用的 cluster ID 必须已经由 `createCluster(cluster_id)` 注册。
- 如果一个 AS 只有一个 cluster，并且没有任何 RR，`Ibgp` 会保留原来的 full-mesh 模式。
- 如果存在 RR，或者一个 AS 中出现多个 cluster，则进入 RR 模式。
- RR 模式下每个 cluster 必须至少有一个 RR。
- RR 模式下每个有 RR 的 cluster 也必须至少有一个 client。
- 未调用 `joinBgpCluster()` 的 router 会被放入默认 cluster `10.0.0.0`。在 RR 拓扑中建议给所有 router 显式设置 cluster，否则默认 cluster 可能因为没有 RR 而触发校验失败。

## Difference From Full Mesh

以前的 `Ibgp` 行为是：在一个 AS 内自动发现所有 router，然后让每个 router 和其他 router 建立 iBGP session。对于 `N` 个 router，session 数量大约是 `N * (N - 1) / 2`。

RR 模式下的行为是：

- client 只和自己 cluster 内的 RR 建立 iBGP session。
- RR 对 client 使用 `ibgp_rr_server` 模板，包含 `rr client` 和 `rr cluster id`。
- client 对 RR 使用 `ibgp_client` 模板。
- RR 与 RR 之间使用普通 `ibgp_peer` 模板做 full mesh。

在这个例子中，`AS62` 有 6 个 router。原 full-mesh 需要 15 条 router-pair session；RR 模式只需要：

- west cluster: `rr_west` 到 `edge100`、`core_west`
- east cluster: `rr_east` 到 `edge101`、`core_east`
- RR mesh: `rr_west` 到 `rr_east`

总共 5 条 router-pair session，配置规模明显更小。

## Topology Summary

`AS62` 的内部网络如下。每条内部链路都单独使用一个两路由网络，以匹配当前 `Ospf` layer 的 point-to-point 接口模板：

```text
AS150 -- IX100 -- edge100 -- net_w_edge -- rr_west -- net_rr -- rr_east -- net_e_edge -- edge101 -- IX101 -- AS151
                                      \                      /
                                   core_west             core_east
                                  net_w_core             net_e_core
```

`AS150` 和 `AS151` 通过 eBGP 把各自前缀通告给 `AS62`。`AS62` 内部用 OSPF 保证 loopback 可达，再用 RR iBGP 在两个 cluster 之间传播 BGP 路由。
