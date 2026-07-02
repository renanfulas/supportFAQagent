from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvalExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    should_escalate: bool
    required_terms: list[str] = Field(default_factory=list)
    # Terms that must NOT appear in the answer. This is how a case proves the
    # negative side of quality gates -- e.g. that a recalled customer summary
    # does not pollute the next answer (injection canary, stale-topic drift).
    forbidden_terms: list[str] = Field(default_factory=list)
    expected_references: list[str] = Field(default_factory=list)
    allowed_handoff_reasons: list[str] = Field(default_factory=list)

    @field_validator(
        "required_terms",
        "forbidden_terms",
        "expected_references",
        "allowed_handoff_reasons",
    )
    @classmethod
    def normalize_list(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value.strip()]


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=4000)
    category: str = Field(min_length=1, max_length=80)
    # Optional seeded customer summary (tiering Fase 4). When present, the
    # runner injects it as the recalled summary for this single case, so the
    # suite can validate that recall improves -- and never pollutes -- the next
    # answer without needing a warehouse row. Mirror the real recall shape:
    # "Problema: ... | Solucao: ... | Status: ...".
    customer_summary: str | None = Field(default=None, max_length=2000)
    expectation: EvalExpectation

    @field_validator("id", "question", "category")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field cannot be blank")
        return normalized


class EvalSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=80)
    cases: list[EvalCase] = Field(min_length=1)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("domain cannot be blank")
        return normalized


class EvalCaseResult(BaseModel):
    case_id: str
    passed: bool
    failures: list[str] = Field(default_factory=list)
    escalated: bool
    confidence: float
    handoff_reasons: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class EvalRunResult(BaseModel):
    domain: str
    total: int
    passed: int
    failed: int
    results: list[EvalCaseResult]
