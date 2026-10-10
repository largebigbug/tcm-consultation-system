# 中医问诊系统 · OWL 本体（给 WebProtégé 用）

本目录的东西由 `tools/yaml2owl.py` **从 7 个本体模型 YAML 机械生成**，用于在 WebProtégé 里可视化浏览与协作编辑本体的「概念层」。

## 文件

| 文件 | 说明 |
|---|---|
| `tcm-ontology.ttl` | 生成物（Turtle，约 193 KB）。**别手改**——改 YAML 后重新生成 |
| `OwlCheck.java` | 验证器：用 WebProtégé 自带的 OWLAPI 4.5.13 真加载一遍并统计 |
| `OwlCheck.class` | 编译产物（可删） |

## 重新生成（YAML 改动后）

```bat
python tools\yaml2owl.py yaml ontology\tcm-ontology.ttl
```

（本机用 `D:\hermes\workspace\docx-venv\Scripts\python.exe`，那里有 PyYAML）

## 验证

```bat
javac -encoding UTF-8 -cp "D:/hermes/workspace/webprotege/tools/tomcat9/webapps/webprotege/WEB-INF/lib/*" ontology\OwlCheck.java
java -Dorg.slf4j.simpleLogger.defaultLogLevel=error -cp "D:/hermes/workspace/webprotege/tools/tomcat9/webapps/webprotege/WEB-INF/lib/*;." OwlCheck ontology\tcm-ontology.ttl
```

当前基线（生成器与 OWLAPI 双侧一致）：

```
类 44 ｜ 对象属性 48 ｜ 数据属性 69 ｜ 个体 306 ｜ 公理 3542 ｜ 中文标签 506
```

## 映射口径

| 源模型 | OWL 表达 |
|---|---|
| M1 聚合根（9） | `owl:Class`（subClassOf `tcm:Aggregate`），中文 `rdfs:label@zh`、英文 `@en`、原 ID 进 `skos:notation` |
| M1 标量字段（69） | `owl:DatatypeProperty`（domain=所属类，range=xsd:string/int/decimal/date/dateTime/boolean） |
| M1 `DictionaryRef` 字段（22） | `owl:ObjectProperty`（range=对应枚举类） |
| M1 `AggregateRootRef` 字段（11） | `owl:ObjectProperty`（range=目标聚合类） |
| M1 数据字典（24 类型 / 107 取值） | 每类型一个 `owl:Class`（`tcm:Enumeration`）+ 每取值一个 `owl:NamedIndividual`（带 `skos:notation`=code） |
| M1 聚合关联（11） | `owl:ObjectProperty`（domain/range=两端聚合类，基数进 `tcm:cardinality`） |
| M5 角色（7） | `owl:NamedIndividual`（`tcm:Role`）；角色→权限用 `tcm:grantsPermission` |
| M5 人员（7） | `owl:NamedIndividual`（`tcm:Actor`）；→角色用 `tcm:hasRole` |
| M5 权限（37） | `owl:NamedIndividual`（`tcm:Permission`）+ `tcm:targetType`/`tcm:dataScope` |
| M2 行为（37） | `owl:NamedIndividual`（`tcm:Behavior`）+ 注记（行为类型/触发/前后置/适用规则） |
| M3 规则（6） | `owl:NamedIndividual`（`tcm:Rule`）+ 注记（表达式/输入参数）；行为→规则用 `tcm:appliesRule` |
| M6 流程（4）+ 活动（75） | `owl:NamedIndividual`（`tcm:Flow`/`tcm:FlowActivity`）；流程→活动用 `tcm:hasActivity` |
| M7 报表（7） | `owl:NamedIndividual`（`tcm:Report`）+ 注记（来源对象/参数/结果列/分组） |
| MU 屏幕（19） | `owl:NamedIndividual`（`tcm:Screen`）+ 屏幕类型与元素/动作数 |

**没有硬塞进 OWL 的部分**：M2 行为的执行语义、M3 规则的表达式求值、M6 流程的状态机、M7 的 SQL 语义——OWL 表达不了，这里作为**注记（annotation）原样保留**，权威口径仍是 YAML。

## 导入 WebProtégé

1. 登录 `http://10.28.157.34:8080/webprotege/`（admin）
2. 先在设置页 `#application/settings` → **Global Permissions** 打开 *Allow project upload*
3. 首页 **Upload Project** → 选 `tcm-ontology.ttl` → 填项目名（如「中医问诊本体」）→ 完成

导入后在 Classes / Properties / Individuals 三个页签里就能看到上表的全部内容（中文标签显示为 `@zh`）。
