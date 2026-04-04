## Scatter Risk: 🚨 RED (0.80)

2 type(s) changed across 1 project(s). 5 direct consumer(s) affected.

### Risk Dimensions

| Dimension | Score | Severity |
| --- | --- | --- |
| Structural coupling | 0.00 | low |
| Instability | 0.00 | low |
| Cycle entanglement | 0.80 | critical |
| Database coupling | 0.00 | low |
| Blast radius | 0.00 | low |
| Domain boundary | 0.00 | low |
| Change surface | 0.70 | high |

### Changed Types

| Type | Kind | Change | Project |
| --- | --- | --- | --- |
| IDataAccess | interface | deleted | Core |
| DataService | class | modified | Core |

### Risk Factors

- Core is in a dependency cycle: Core → Api → Core (2 projects)
- 1 type(s) deleted: IDataAccess
- 1 type(s) modified: DataService

### Consumer Impact

**5** direct, **3** transitive consumers.

Affected: Api, Worker, Portal, Reports, Analytics

---
*Analysis completed in 156ms*
