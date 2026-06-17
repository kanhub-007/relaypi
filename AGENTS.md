# AGENTS.md — {{PROJECT_NAME}} (Python flavor)

> **For AI coding assistants and human developers.** Authoritative guide for
> working in this codebase: architecture, mandatory design patterns, coding
> conventions, testing, and review standards. Extensions/skills add detail but
> never override this.
>
> **How to use:** replace every `{{PLACEHOLDER}}`; delete `[OPTIONAL]` sections
> that don't apply; fill `[FILL IN]` markers; keep the structure and rules.

---

## 1. Project Identity

- **Name:** {{PROJECT_NAME}}
- **One-line description:** {{ONE_LINE_DESCRIPTION}}
- **Language / runtime:** Python 3.12+
- **Package root:** `{{PACKAGE_ROOT}}` (e.g. `src/` or `myproject/`)
- **Import prefix:** `{{IMPORT_PREFIX}}` (e.g. `myproject.`)

### Scope — owns vs. delegates

| This project owns | This project delegates to |
|-------------------|---------------------------|
| {{OWNED_RESPONSIBILITY}} | {{DELEGATED_TO}} |

---

## 2. [OPTIONAL] Non-Negotiable Safety Rules

> Keep only if safety/money/security-critical. Delete otherwise.

1. **Safe mode is the default** (`dry_run`, read-only, sandboxed). Never default to a destructive/production action.
2. **Destructive actions require explicit opt-in** (config flag + acknowledgment like `{{PROJECT}}_LIVE_ACK=true`).
3. **No secrets in code or tests** — env vars or ignored local files only.
4. **Idempotency is mandatory** — duplicate triggers must not duplicate side effects.
5. **Persist before/after external effects** — record intent, then the response.
6. **Reconcile on startup** — verify against the source of truth, don't trust cached state.
7. **Gates before every side effect** — limits/quotas/staleness checks first.
8. **Kill switch / undo is first-class**.

---

## 3. Architecture Skeleton

**Clean Architecture.** Dependencies flow inward; outer layers may depend on
inner layers; inner layers must NEVER depend on outer layers.

```
┌──────────────────────────────────────────────────────┐
│  presentation/     API routes, CLI commands, UI,      │  ← adapters
│                    MCP/GraphQL handlers               │  Can import: application, domain,
│                                                      │              infrastructure (reads)
├──────────────────────────────────────────────────────┤
│  startup/          Composition root, DI factories,    │  ← wiring
│                    bootstrap / create_app             │  Can import: EVERYTHING
├──────────────────────────────────────────────────────┤
│  core/application/ Use cases, DTOs, selectors,        │  ← orchestration
│                    ports, application services        │  Can import: domain ONLY
├──────────────────────────────────────────────────────┤
│  core/domain/      Entities, value objects,           │  ← innermost
│                    interfaces, pure logic             │  Can import: stdlib, typing, abc,
│                                                      │              dataclasses, domain libs
├──────────────────────────────────────────────────────┤
│  infrastructure/   ORM tables, repositories, external │  ← I/O
│                    services, file/network/SDK adapters│  Can import: domain (implements
│                                                      │              interfaces)
└──────────────────────────────────────────────────────┘
```

### Layer purposes

| Layer | Purpose | What goes here |
|-------|---------|---------------|
| `core/domain/` | Pure business logic — no frameworks | dataclasses, ABC/Protocol interfaces, domain algorithms, value objects, domain services |
| `core/application/` | Orchestration | use cases, DTOs, selectors, ports |
| `infrastructure/` | I/O | SQLAlchemy tables, repository impls + mappers, external clients/adapters, filesystem, clock |
| `presentation/` | Outside world | FastAPI/Flask routes, CLI (Click/Typer), MCP tools, presenters |
| `startup/` | Wiring | DI factories, `bootstrap()`, `create_app()` |

### Dependency rules

| Layer | May import from | Must NOT import |
|-------|-----------------|-----------------|
| `startup/` | EVERYTHING | — |
| `presentation/` | application, domain, infrastructure (reads) | direct external/SDK logic |
| `core/application/` | domain ONLY | infrastructure, presentation, frameworks |
| `core/domain/` | stdlib, typing, domain-appropriate libs | anything else |
| `infrastructure/` | domain | application, presentation |

> **Golden rule:** application use cases depend on **domain interfaces**, never
> on concrete infrastructure classes.

### CQRS-lite read exception
Complex read-only queries may use ORM directly in presentation. **Writes MUST go
through a repository.**

### [OPTIONAL] External Integration Boundaries

| External dependency | Rule |
|---------------------|------|
| `{{EXTERNAL_SDK}}` | Only `infrastructure/adapters/` may import it. Wrap behind a domain interface. Never pass raw SDK types into application/domain — convert to domain entities/DTOs. |
| `{{SECONDARY_LIB}}` | {{RULE}} |

---

## 4. Design Patterns — Decision Tree

Walk this tree for every non-trivial piece of code. A pattern is **mandatory**
when its trigger fires.

- **Q1 How is it constructed?** complex graph → **Factory** (`startup/`); many optional params → **Builder**; family of objects → **Abstract Factory**; trivial → plain constructor.
- **Q2 How does it get deps?** always → **DI (constructor injection)**. No Service Locator, no Singleton, no global state.
- **Q3 How does it access data?** writes → **Repository**; reads for a write → Repository; read-only query → Repository OR direct ORM; external data API → **Adapter**.
- **Q4 How does behaviour vary?** by parameter → **Strategy**; by internal state → **State**; fixed skeleton → **Template Method**.
- **Q5 External systems?** wrapping API/SDK → **Adapter**; cross-cutting (logging, retry, cache, tx) → **Decorator**; lazy/access control → **Proxy**.
- **Q6 Data across boundaries?** layer boundary → **DTO**; entity ↔ ORM → **Mapper**; complex formatting → **Facade/Presenter**.
- **Q7 Complex flows?** async/events → **Observer**; parameterised/undo → **Command**; sequential fallback → **Chain of Responsibility**; traversing structures → **Visitor**; leaf+composite → **Composite**; many-to-many coupling → **Mediator**; snapshots → **Memento**.
- **Q8 Decompose?** function >50 lines → **Pipeline/Extract Method**; repeated error handling → **Decorator**; repeated if/else → **Strategy**.

### Canonical forms

```python
# Dependency Injection — constructor injection
class OrderService:
    def __init__(self, repository: OrderRepository, notifier: Notifier) -> None:
        self._repository = repository
        self._notifier = notifier

# Repository — interface in domain, impl in infrastructure
#   Domain Entity  <->  Mapper  <->  ORM Model  <->  Database
class OrderRepository(ABC):                          # core/domain/interfaces/
    @abstractmethod
    def save(self, db: Session, order: Order) -> None: ...
    @abstractmethod
    def find_by_id(self, db: Session, order_id: str) -> Order | None: ...

class SqlOrderRepository(OrderRepository):           # infrastructure/repositories/
    def save(self, db: Session, order: Order) -> None:
        db.add(order_to_orm(order))                  # mapper

# Strategy — caller injects; use case is agnostic
class CalculateOrderTotalUseCase:
    def __init__(self, pricing: PricingStrategy) -> None:
        self._pricing = pricing

# Factory — in startup/ only
def create_order_use_case(db: Session) -> CreateOrderUseCase:
    return CreateOrderUseCase(SqlOrderRepository(), StripeGateway(), ...)

# DTO — pure data, crosses boundaries
@dataclass(frozen=True)
class CreateOrderResult:
    order_id: str
    status: str
    total: Decimal
```

> When multiple patterns fit, apply in order: **DI → Repository → Factory →
> Strategy/State → Adapter → DTO → Builder → Decorator → Pipeline → Visitor →
> Observer → Command → Facade → Chain → Template Method → Composite → Mediator
> → Proxy → Memento → State.**

### Anti-Patterns — always flag

| Anti-pattern | Why banned | Better alternative |
|---|---|---|
| **Singleton** (global state) | Untestable, violates DI | Factory + ctor-injected caching |
| **Service Locator** | Hides dependencies | Constructor Injection |
| **God Class** / **God Method (>50 lines)** | Too much in one unit | Split / Pipeline |
| **Anemic Domain Model** | Logic outside entities | Put logic in entities / domain services |
| **Inheritance for reuse** | Deep hierarchies | Composition + ABC/Protocol |
| **Leaky Infrastructure** | ORM/SDK types in domain/application | Mapper / DTO / Adapter |

### Size constraints

| Element | Max | Action |
|---|---|---|
| Method/function | ~50 lines | Extract step methods |
| Class | ~150 lines | Split responsibilities |
| File | ~500 lines | Review for splitting |

---

## 5. One Class Per File — Strict Rule

Every class, interface (ABC/Protocol), DTO, entity, enum, and strategy lives in
its own `snake_case.py` file matching the class name.

```python
# ✅ CORRECT
core/domain/interfaces/order_repository.py    -> class OrderRepository(ABC)
core/domain/entities/order.py                 -> @dataclass class Order
core/application/dto/create_order_result.py   -> @dataclass class CreateOrderResult
core/application/use_cases/create_order.py    -> class CreateOrderUseCase
infrastructure/repositories/sql_order_repo.py -> class SqlOrderRepository

# ❌ WRONG — multiple classes in one file
core/domain/interfaces/repositories.py        -> OrderRepository, UserRepository, ...  # NO
```

**Exceptions:** `__init__.py` re-exports; helpers tightly coupled to the single
class; types used only by that one class.

---

## 6. Coding Conventions

### Imports (order)

```python
# 1. Standard library
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

# 2. Third-party
from sqlalchemy.orm import Session

# 3. Internal — absolute from package root
from myproject.core.domain.entities.order import Order as DomainOrder
from myproject.infrastructure.tables.order import Order as OrmOrder
```

Never import ORM models as bare names — always alias (`DomainOrder` / `OrmOrder`).

### Naming

| Thing | Convention | Example |
|-------|-----------|---------|
| Classes / ABCs / Protocols | PascalCase, **no `I` prefix** | `OrderRepository`, `PaymentGateway` |
| Functions / methods | snake_case | `find_by_id()` |
| Variables | snake_case | `items_shipped` |
| Constants | UPPER_SNAKE | `MAX_RETRY_COUNT` |
| Private members | `_` prefix | `self._repository` |
| Files | snake_case | `create_order.py` |

### Type hints
All public functions/methods have type hints. Use `X | None`, not `Optional`.

```python
def execute(self, db: Session, order_id: str) -> CreateOrderResult: ...
def find_by_id(self, db: Session, order_id: str) -> Order | None: ...
```

### Docstrings
All public classes/methods: summary line, blank line, then details/params/return/raises.

```python
class CreateOrderUseCase:
    """Creates an order: validates inventory, reserves items, processes payment,
    and sends a confirmation notification."""

    def execute(self, db: Session, request: CreateOrderRequest) -> CreateOrderResult:
        """Execute the create-order operation.

        Args:
            db: Database session.
            request: The order creation request DTO.

        Returns:
            CreateOrderResult with the new order ID and status.

        Raises:
            InsufficientInventoryError: If any item is out of stock.
        """
```

### Domain entity vs persistence model

```python
# Domain entity — pure Python, no ORM  (core/domain/entities/order.py)
@dataclass(frozen=True)
class Order:
    id: int | None = None
    order_id: str = ""
    total: Decimal = Decimal("0.00")

# ORM model — SQLAlchemy                 (infrastructure/tables/order.py)
class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    order_id = Column(String, unique=True)
    total = Column(Numeric(10, 2))
```

Never the same class. Convert via **mapper** functions in `infrastructure/repositories/`.
Domain entities are **pure**: no DB, filesystem, network, framework, or env deps.

### Misc
- Prefer `Decimal` for money/quantities — avoid binary floats.
- UTC timestamps (`datetime.now(timezone.utc)`).
- Structured logging (`logging` + JSON formatter) for significant events.

---

## 7. How to Add a Feature

1. **Domain interface** — `core/domain/interfaces/<thing>.py`
2. **Domain entity / value object** — `core/domain/entities/<thing>.py`
3. **DTO** — `core/application/dto/<thing>.py`
4. **Use case** (domain interfaces only) — `core/application/use_cases/<thing>.py`
5. **Infrastructure** — ORM table, mapper, repository impl, adapter/service.
6. **Wire it** (composition root) — `startup/<thing>_factory.py`
7. **Expose it** — route / CLI command / MCP tool in `presentation/`.
8. **Register it** — router/handler `__init__.py` + `startup` entry point.
9. **Test it** at the correct layer.

---

## 8. Testing — Classical (Detroit) School + Black-Box

| Principle | Meaning |
|---|---|
| **Mock only external boundaries** | DB, network, filesystem, clock, random, env. Do NOT mock domain objects. |
| **Test by outcome, not interaction** | Assert return value/state. No `verify()`/`assert_called()` on domain objects. |
| **Fakes over mocks** | `InMemoryOrderRepository` gives real behaviour. |
| **Survive refactoring** | Break only when behaviour changes, not when internals change. |
| **Black-box design** | Derive cases from the spec/contract, not the implementation. |
| **Public API only** | Private methods tested indirectly. |

### Structure

```text
tests/
├── test_domain/          # pure unit tests — no db/fs/network
├── test_application/     # use cases with in-memory/fake interfaces
├── test_infrastructure/  # integration — in-memory SQLite, temp files, fakes
└── test_presentation/    # end-to-end — create app, call endpoints/tools
```

Minimum per feature: happy path; edge cases (empty, zero, negative, duplicates,
large); error paths (dependency down, invalid input, timeout); idempotency/safety
gates if applicable.

Run: `pytest tests/`

---

## 9. Linting & Formatting

```bash
# Lint (+ autofix)
ruff check src/ tests/ --fix

# Format
black src/ tests/

# Type-check
mypy src/
```

- All code passes `ruff check` with zero errors before commit.
- All code is `black`-formatted (line length 88).
- CI rejects failures.

---

## 10. Review Checklist

- [ ] No secrets committed; safe mode is the default.
- [ ] No layer-boundary violations (check imports against §3).
- [ ] External SDKs confined to `infrastructure/adapters/`.
- [ ] Side effects idempotent; gates run before them.
- [ ] One-class-per-file; public APIs have type hints + docstrings.
- [ ] No anti-patterns (singleton, service locator, god class/method).
- [ ] Tests cover happy/edge/error with fakes (not mocks of internals).
- [ ] `ruff` + `black` + `mypy` pass; test suite green.

> Deeper review dimensions (apply as needed): logic & correctness, security,
> performance, code quality, tests, spec conformance.

---

## 11. Key Files to Know

| File | Purpose |
|------|---------|
| `{{PACKAGE_ROOT}}/startup/bootstrap.py` | App bootstrap / DB init |
| `{{PACKAGE_ROOT}}/startup/create_app.py` | HTTP/API app factory |
| `{{PACKAGE_ROOT}}/infrastructure/connection.py` | SQLAlchemy engine + session factory |
| `{{PACKAGE_ROOT}}/infrastructure/repositories/mappers.py` | Domain ↔ ORM converters |
| `{{PACKAGE_ROOT}}/config.py` | Configuration loading + validation |
| {{MORE_KEY_FILE}} | {{PURPOSE}} |

> Plans/specs live in `docs/plans/` (or `specs/`). Read the relevant one before
> starting work in a feature area.

---

## 12. Development Commands

```bash
# Install (editable, with dev extras)
pip install -e ".[dev]"

# Run
{{RUN_COMMAND}}          # e.g. uvicorn myproject.presentation.api:app --reload

# Full check before commit
ruff check src/ tests/ && black --check src/ tests/ && mypy src/ && pytest
```

---

## 13. Glossary

| Term | Definition |
|---|---|
| **Classical (Detroit) school** | Real objects for domain, fakes at boundaries, assert outcomes not interactions |
| **Black-box test design** | Tests derived from spec/contract, not implementation |
| **Fake** | In-memory implementation of an interface |
| **Mock** | Records/verifies interactions — only for external boundaries |
| **DTO** | Data Transfer Object — crosses layer boundaries |
| **Mapper** | Converts between domain entity and ORM model |
| **Repository** | Domain interface for write data access; impl in infrastructure |
| **Adapter** | Wraps an external API/SDK, isolating it in infrastructure |
| **CQRS-lite** | Reads may bypass repository; writes must not |
| **Composition root** | `startup/` — where the object graph is assembled |
| **DI** | Constructor Injection — dependencies passed in, never created/fetched globally |
