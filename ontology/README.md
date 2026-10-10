# 中医问诊系统 · 本体产物（给 WebProtégé / Protégé 桌面版 / 数据校验用）

全部由 7 个本体模型 YAML **机械生成**，请勿手改生成物——改 YAML 后重跑。

## 文件一览

| 文件 | 用途 | 规模 |
|---|---|---|
| `tcm-ontology.ttl` | **主文件**，导入 WebProtégé 用这个（Turtle） | 193 KB ｜ 类44/对象属性48/数据属性69/个体306 |
| `tcm-ontology.rdf` | 同内容，RDF/XML（Protégé 桌面版、老工具偏好） | 385 KB |
| `tcm-ontology.ofn` | 同内容，OWL 函数式语法 | 347 KB |
| `shards/m1..mu.ttl` | **按模型拆分的 7 个分片**，供分工维护与评审（引用其他模型的实体是正常的，完整导入请用主文件） | 10–62 KB/片 |
| `tcm-vocabulary-skos.ttl` | **SKOS 值域词表**：24 个概念方案 / 107 个概念（数据字典的取值） | 24 KB |
| `tcm-shapes.ttl` | **SHACL 结构校验形状**：9 个节点形状 / 102 条字段约束 | 21 KB |
| `OwlCheck.java` / `LoadAll.java` | 验证器：用 WebProtégé 自带 OWLAPI 4.5.13 真加载并统计 | — |
| `ExportFormats.java` | 从 Turtle 生成 RDF/XML 与函数式语法两个变体 | — |

## 重新生成（YAML 改动后）

```bat
set PY=D:\hermes\workspace\docx-venv\Scripts\python.exe
%PY% tools\yaml2owl.py       yaml ontology\tcm-ontology.ttl
%PY% tools\ontology_extras.py all
```

## 验证（两边都跑，数字必须一致）

```bat
set J=D:\hermes\workspace\webprotege\tools\jdk-11\bin\java.exe
set L=D:\hermes\workspace\webprotege\tools\tomcat9\webapps\webprotege\WEB-INF\lib
%J% -Dorg.slf4j.simpleLogger.defaultLogLevel=error -cp "%L%\*;." LoadAll tcm-ontology.ttl tcm-ontology.rdf tcm-ontology.ofn tcm-vocabulary-skos.ttl tcm-shapes.ttl shards\m1.ttl
```

当前基线：`类 44 ｜ 对象属性 48 ｜ 数据属性 69 ｜ 个体 306 ｜ 公理 3542`（三个格式回读规模一致；RDF/XML/函数式比 Turtle 多 3 条公理，为序列化时补显式声明所致）

**SHACL 真校验**（造一条合规 + 一条违规数据，看形状能不能拦）：

```bat
D:\hermes\workspace\owl-venv\Scripts\python.exe tools\check_shacl.py
```

基线结果：合规样本 `conforms=True` ｜ 违规样本 `conforms=False` 且精确指出「少于 1 个值（患者姓名）」「不是 xsd:integer（年龄）」。

## 映射口径

| 源模型 | OWL 表达 |
|---|---|
| M1 聚合根（9） | `owl:Class`（subClassOf `tcm:Aggregate`）：中文 `rdfs:label@zh`、英文 `@en`、原 ID 进 `skos:notation` |
| M1 标量字段（69） | `owl:DatatypeProperty`（domain=所属类，range=xsd:string/integer/decimal/date/dateTime/boolean） |
| M1 `DictionaryRef`（22） | `owl:ObjectProperty`（range=对应枚举类） |
| M1 `AggregateRootRef`（11） | `owl:ObjectProperty`（range=目标聚合类） |
| M1 数据字典（24 类型/107 取值） | 每类型一个 `owl:Class`（`tcm:Enumeration`）+ 每取值一个 `owl:NamedIndividual`（同命名空间）；另出 SKOS 词表 |
| M1 聚合关联（11） | `owl:ObjectProperty`（domain/range=两端聚合类，基数进 `tcm:cardinality`） |
| M5 角色（7）/人员（7）/权限（37） | 个体：`tcm:Role` / `tcm:Actor`（→`tcm:hasRole`）/ `tcm:Permission`（角色→权限用 `tcm:grantsPermission`） |
| M2 行为（37） | 个体 `tcm:Behavior` + 注记（行为类型/触发/前后置/适用规则）；行为→规则 `tcm:appliesRule` |
| M3 规则（6） | 个体 `tcm:Rule` + 注记（表达式/输入参数/输出类型） |
| M6 流程（4）/活动（75） | 个体 `tcm:Flow` / `tcm:FlowActivity`（`tcm:hasActivity`） |
| M7 报表（7） | 个体 `tcm:Report` + 注记（来源对象/参数/结果列/分组/排序） |
| MU 屏幕（19） | 个体 `tcm:Screen` + 屏幕类型与元素/动作数 |

## 能力边界（重要，实测得出）

- **WebProtégé 4.0.2 不支持 SHACL**（源码零命中）；**也没有 SWRL 编辑器/规则引擎**（SWRL 只出现在渲染与 axiom 排序等管道代码里，jar 里无 swrlapi）。因此**不做规则层的 OWL 复制**——M3 规则与 M2 行为语义的**权威口径仍是 YAML + 应用引擎**，本体里只作为注记保留，避免两套口径分叉。
- 本体的价值定位：**概念层可视化、多人评审、术语对齐（SKOS）、以及数据结构契约的数据校验（SHACL 离线跑）**。
- **不提供 OBO**：OBO 面向生物医学类层次（要求 `id:` 与 term 结构），本次导出在 OWLAPI 4.5 下转换器报 `No instantiation found for OWLOntologyBuilder`，且即便成功也会丢掉全部个体与注记——对本本体价值≈0。
- `unique` 字段在 SHACL 里用 `sh:maxCount 1` 近似（SHACL 无「全局唯一」语义）；真正的唯一性由数据库唯一索引保证。

## 导入 WebProtégé

1. 登录 `http://10.28.157.34:8080/webprotege/`（admin）
2. 设置页 `#application/settings` → **Global Permissions** 打开 *Allow project upload*
3. 首页 **Upload Project** → 选 `tcm-ontology.ttl` → 项目名填「中医问诊本体」

导入后 Classes / Properties / Individuals 三个页签即为上表内容（中文标签显示为 `@zh`）。
