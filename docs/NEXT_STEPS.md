# Next Steps: Completing the Health Assistant Refactoring

## Refactoring Progress

### ✅ Completed (Phase 1)
- [x] Created handler pattern architecture
- [x] Implemented Pydantic metrics models (7 models)
- [x] Refactored FIT upload endpoint → `FitUploadHandler`
- [x] Refactored OneDrive sync endpoint → `OneDriveSyncHandler`
- [x] Refactored planning/query endpoints → `QueryHandler`
- [x] Reduced `function_app.py` from 1,684 → 814 lines (51% reduction)
- [x] Reduced cognitive complexity from 16 → 3 for sync endpoint
- [x] Created comprehensive documentation
- [x] Created example tests demonstrating testability

### 🚧 In Progress (Phase 2)
- [ ] Create remaining handler classes
- [ ] Complete unit test coverage
- [ ] Update API documentation

### 📋 Todo (Phase 3)
- [ ] Integration testing with Azure Functions
- [ ] Performance benchmarking
- [ ] Deploy and validate in production

---

## Remaining Handlers to Create

### Priority 1: Core Business Logic

#### 1. PhysiometricsHandler
**Current State**: Lines 426-523 in `function_app.py`

**Endpoints to Extract**:
- `GET /physiometrics/current` - Get current physiometric values
- `GET /physiometrics/history` - Get time-series data
- `POST /physiometrics/update` - Update metrics (single or bulk)

**Handler Design**:
```python
# FitParser/handlers/physiometrics_handler.py

class PhysiometricsHandler:
    """Handles physiometric data operations."""
    
    def __init__(self, semantic_layer: SemanticLayer):
        self.semantic_layer = semantic_layer
    
    def get_current(self, athlete_id: str) -> Tuple[Dict, int]:
        """Get current physiometric snapshot."""
        
    def get_history(self, athlete_id: str, days: int, metrics: List[str] = None) -> Tuple[Dict, int]:
        """Get time-series physiometric data."""
        
    def update_metric(self, athlete_id: str, metric: str, value: float, 
                     effective_date: str = None, source: str = "chatgpt") -> Tuple[Dict, int]:
        """Update single physiometric value."""
        
    def update_metrics(self, athlete_id: str, metrics: Dict[str, float],
                      effective_date: str = None, source: str = "chatgpt") -> Tuple[Dict, int]:
        """Bulk update physiometric values."""
```

**Estimated Effort**: 2 hours
**Complexity**: Low
**Tests Required**: 6-8 unit tests

---

#### 2. WithingsHandler
**Current State**: Lines 530-624 in `function_app.py`

**Endpoints to Extract**:
- `GET /withings/authorize` - Get OAuth URL
- `GET /withings/callback` - Handle OAuth callback
- `POST /withings/webhook` - Receive webhook notifications

**Handler Design**:
```python
# FitParser/handlers/withings_handler.py

class WithingsHandler:
    """Handles Withings OAuth and webhook operations."""
    
    def __init__(self, withings_client: WithingsClient, storage: WorkoutTableStorage):
        self.client = withings_client
        self.storage = storage
    
    def get_authorization_url(self, athlete_id: str) -> Tuple[Dict, int]:
        """Generate Withings OAuth authorization URL."""
        
    def handle_oauth_callback(self, code: str, state: str) -> Tuple[str, int]:
        """Process OAuth callback and store tokens.
        
        Returns: (HTML response, status_code)
        """
        
    def process_webhook(self, userid: str, appli: str, 
                       startdate: str, enddate: str) -> Tuple[str, int]:
        """Process Withings webhook notification.
        
        Returns: ("OK", status_code)
        """
```

**Estimated Effort**: 3 hours
**Complexity**: Medium (OAuth flow complexity)
**Tests Required**: 8-10 unit tests + 2 integration tests

---

#### 3. ConfigHandler
**Current State**: Lines 631-774 in `function_app.py`

**Endpoints to Extract**:
- `POST /config/reload` - Reload physiometrics config from disk
- `POST /config/update` - Update configuration
- `GET /config/history` - Get configuration change history

**Handler Design**:
```python
# FitParser/handlers/config_handler.py

class ConfigHandler:
    """Handles physiometrics configuration operations."""
    
    def reload_config(self) -> Tuple[Dict, int]:
        """Reload configuration from disk/storage."""
        
    def update_config(self, config_data: Dict) -> Tuple[Dict, int]:
        """Update configuration and persist to storage."""
        
    def get_history(self, limit: int = 10) -> Tuple[Dict, int]:
        """Get configuration change history."""
```

**Estimated Effort**: 1.5 hours
**Complexity**: Low
**Tests Required**: 5-6 unit tests

---

### Priority 2: Supporting Infrastructure

#### 4. HealthHandler
**Current State**: Lines 336-416 in `function_app.py`

**Endpoints to Extract**:
- `GET /health` - Health check with dependency verification
- `GET /.well-known/ai-plugin.json` - ChatGPT plugin manifest
- `GET /openapi.yaml` - OpenAPI specification
- `GET /logo.svg` - Logo asset

**Handler Design**:
```python
# FitParser/handlers/health_handler.py

class HealthHandler:
    """Handles health check and plugin metadata endpoints."""
    
    def __init__(self, storage: WorkoutTableStorage):
        self.storage = storage
    
    def check_health(self) -> Tuple[Dict, int]:
        """Verify system health and dependencies."""
        
    def get_plugin_manifest(self, base_url: str) -> Tuple[Dict, int]:
        """Get ChatGPT plugin manifest with dynamic URLs."""
        
    def get_openapi_spec(self, base_url: str) -> Tuple[str, int]:
        """Get OpenAPI spec with dynamic server URL."""
        
    def get_logo(self) -> Tuple[str, int]:
        """Get logo SVG content."""
```

**Estimated Effort**: 2 hours
**Complexity**: Low
**Tests Required**: 6-8 unit tests

---

## Testing Strategy

### Unit Tests (Per Handler)
1. **Request Parsing Tests**
   - Valid inputs
   - Invalid inputs
   - Missing parameters
   - Edge cases

2. **Business Logic Tests**
   - Happy path execution
   - Error handling
   - Boundary conditions
   - State management

3. **Integration Points**
   - Mock service interactions
   - Verify correct method calls
   - Check response formats

### Integration Tests
1. **HTTP Adapter Tests**
   - End-to-end request/response flow
   - Azure Functions framework integration
   - Error propagation

2. **Service Integration Tests**
   - Real storage interactions (test container)
   - Real semantic layer queries
   - OAuth flow (with test credentials)

### Example Test Structure
```python
# tests/test_physiometrics_handler.py

import pytest
from unittest.mock import Mock
from FitParser.handlers.physiometrics_handler import PhysiometricsHandler

class TestPhysiometricsHandler:
    @pytest.fixture
    def semantic_layer(self):
        return Mock()
    
    @pytest.fixture
    def handler(self, semantic_layer):
        return PhysiometricsHandler(semantic_layer)
    
    def test_get_current_success(self, handler, semantic_layer):
        # Given
        semantic_layer.get_current_physiometrics.return_value = {
            "weight_kg": 75.5,
            "cycling_vo2max_ml_kg_min": 52.3
        }
        
        # When
        result, status = handler.get_current("rob")
        
        # Then
        assert status == 200
        assert result["weight_kg"] == 75.5
        semantic_layer.get_current_physiometrics.assert_called_once_with("rob")
    
    def test_get_current_missing_athlete(self, handler):
        # When
        result, status = handler.get_current("")
        
        # Then
        assert status == 400
        assert "error" in result
```

---

## Implementation Checklist

### For Each Handler:

#### Step 1: Create Handler File
```bash
touch FitParser/handlers/<handler_name>_handler.py
```

#### Step 2: Define Classes and Methods
- [ ] Create handler class
- [ ] Define `__init__` with dependencies
- [ ] Implement business logic methods
- [ ] Add type hints (Tuple[Dict, int] pattern)
- [ ] Add docstrings

#### Step 3: Update Package Exports
```python
# FitParser/handlers/__init__.py
from .physiometrics_handler import PhysiometricsHandler
from .withings_handler import WithingsHandler
from .config_handler import ConfigHandler
from .health_handler import HealthHandler

__all__ = [
    "FitUploadHandler",
    "OneDriveSyncHandler",
    "OneDriveSyncRequest",
    "QueryHandler",
    "PhysiometricsHandler",
    "WithingsHandler",
    "ConfigHandler",
    "HealthHandler",
]
```

#### Step 4: Refactor HTTP Endpoint
Replace old endpoint code with:
```python
@app.route(route="<endpoint>", methods=["<METHOD>"])
def <endpoint_name>(req: func.HttpRequest) -> func.HttpResponse:
    """<Docstring>."""
    try:
        # 1. Parse request
        athlete_id = req.params.get("athlete_id")
        
        # 2. Call handler
        handler = <Handler>(_get_dependency())
        result, status = handler.<method>(athlete_id)
        
        # 3. Return response
        return _json_response(result, status)
    
    except Exception as exc:
        logger.error("<Endpoint> failed: %s", exc, exc_info=True)
        return _json_response({"error": "Internal server error"}, 500)
```

#### Step 5: Write Tests
- [ ] Create test file: `tests/test_<handler_name>_handler.py`
- [ ] Write unit tests for each method
- [ ] Test error handling
- [ ] Test edge cases
- [ ] Run tests: `pytest tests/test_<handler_name>_handler.py -v`

#### Step 6: Verify
- [ ] Syntax check: `python3 -m py_compile FitParser/handlers/<handler>.py`
- [ ] Import check: `python3 -c "from FitParser.handlers import <Handler>"`
- [ ] Test pass: `pytest tests/test_<handler>_handler.py`
- [ ] Integration test: Run actual Azure Function locally

---

## Timeline Estimate

### Week 1: Core Handlers
- **Day 1-2**: PhysiometricsHandler (2h dev + 2h tests)
- **Day 3-4**: WithingsHandler (3h dev + 3h tests)
- **Day 5**: ConfigHandler (1.5h dev + 1.5h tests)

### Week 2: Infrastructure & Testing
- **Day 1**: HealthHandler (2h dev + 2h tests)
- **Day 2-3**: Integration tests for all handlers
- **Day 4**: Documentation updates
- **Day 5**: Code review and refinement

### Week 3: Validation & Deployment
- **Day 1-2**: Local Azure Functions testing
- **Day 3**: Performance benchmarking
- **Day 4**: Deploy to staging environment
- **Day 5**: Production deployment and monitoring

---

## Success Metrics

### Code Quality
- [ ] All handlers have < 10 cognitive complexity
- [ ] 90%+ test coverage on handler code
- [ ] Zero pylint errors
- [ ] Zero SonarQube critical issues

### Performance
- [ ] Response time < 200ms for query endpoints
- [ ] Response time < 500ms for sync operations
- [ ] Memory usage stable over 24h period

### Functionality
- [ ] All existing endpoints work identically
- [ ] No regressions in production monitoring
- [ ] Successful integration tests

---

## Risk Mitigation

### Risk 1: Breaking Changes
**Mitigation**: 
- Keep backup (`function_app.py.backup`)
- Deploy to staging first
- Run comprehensive integration tests
- Monitor error rates in production

### Risk 2: Performance Degradation
**Mitigation**:
- Benchmark before/after performance
- Profile handler execution times
- Monitor Azure Functions metrics
- Have rollback plan ready

### Risk 3: Testing Gaps
**Mitigation**:
- Require 90%+ test coverage
- Review tests with team
- Run integration tests in CI/CD
- Manual QA testing before production

---

## Rollback Plan

If issues arise:
1. Revert to `function_app.py.backup`
2. Remove handler imports
3. Redeploy previous version
4. Monitor for stability
5. Debug issues in staging environment

---

## Future Enhancements (Post-Refactoring)

### Phase 4: Advanced Features
- [ ] Add caching layer to handlers
- [ ] Implement rate limiting
- [ ] Add request tracing/telemetry
- [ ] Create admin dashboard for monitoring

### Phase 5: API v2
- [ ] RESTful API redesign
- [ ] GraphQL endpoint
- [ ] Webhook subscriptions
- [ ] Real-time updates (WebSocket)

---

## Questions & Decisions

### Q1: Should we use Pydantic for all request/response models?
**Decision**: Yes, for new handlers. Provides validation and type safety.

### Q2: How to handle backwards compatibility?
**Decision**: Maintain existing API contracts. Internal refactoring only.

### Q3: Should handlers have unit tests AND integration tests?
**Decision**: Yes. Unit tests for business logic, integration tests for Azure Functions.

### Q4: What's the testing coverage target?
**Decision**: 90%+ for handler code, 70%+ for HTTP adapters.

---

## Resources

### Documentation
- [Azure Functions Python Developer Guide](https://docs.microsoft.com/en-us/azure/azure-functions/functions-reference-python)
- [Pydantic Documentation](https://docs.pydantic.dev/)
- [pytest Best Practices](https://docs.pytest.org/en/stable/goodpractices.html)

### Code Examples
- `tests/test_handlers_example.py` - Example test patterns
- `REFACTORING_COMPARISON.md` - Before/after comparison
- `REFACTORING_SUMMARY.md` - Complete refactoring details

### Tools
- `pytest` - Unit testing
- `pytest-cov` - Coverage reporting
- `pylint` - Code quality
- `black` - Code formatting

---

## Contact & Support

For questions about the refactoring:
1. Review `REFACTORING_SUMMARY.md` for architectural overview
2. Check `REFACTORING_COMPARISON.md` for specific examples
3. Look at existing handlers in `FitParser/handlers/`
4. Review example tests in `tests/test_handlers_example.py`

---

## Appendix: Handler Template

```python
"""<Handler description>."""

import logging
from typing import Dict, Tuple, Any

logger = logging.getLogger(__name__)


class <Handler>Handler:
    """<Handler description>."""

    def __init__(self, dependency: <DependencyType>):
        """Initialize handler with dependencies."""
        self.dependency = dependency

    def <method_name>(self, param1: str, param2: int = None) -> Tuple[Dict[str, Any], int]:
        """<Method description>.
        
        Args:
            param1: Description
            param2: Description (optional)
            
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            # Business logic here
            result = self.dependency.some_method(param1, param2)
            return result, 200
            
        except ValueError as exc:
            logger.error("Validation error: %s", exc)
            return {"error": str(exc)}, 400
            
        except Exception as exc:
            logger.error("Handler failed: %s", exc, exc_info=True)
            return {"error": "Internal server error"}, 500
```

---

**Last Updated**: February 1, 2026
