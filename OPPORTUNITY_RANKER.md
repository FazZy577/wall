# Opportunity Ranker

Canonical contract: `domain.interfaces.opportunity_ranker`
Production implementation: `infrastructure.rankers.default_opportunity_ranker`

There is one ranking path and one implemented strategy:

```python
class RankingStrategy(StrEnum):
    OPPORTUNITY_SCORE = "opportunity_score"
```

`IOpportunityRanker.rank()` receives every `ArbitrageOpportunity` and returns
a new ordered list. It does not filter, limit, mutate, recalculate, or change
recommendations. `DefaultOpportunityRanker` applies this stable key:

```text
(recommendation priority, -opportunity_score)
BUY = 0, MAYBE = 1, SKIP = 2
```

Equal keys retain input order. Profit, confidence, ROI, listing ID and other
fields are not hidden tie-breakers.

The batch `DefaultOpportunityScanner` requires an `IOpportunityRanker` through
constructor injection and calls it exactly once after all candidates have been
processed. The scanner passes all opportunities and returns the order supplied
by the ranker. Ranking errors propagate to the caller.

`RankingResult.from_ranked_opportunities()` only computes metadata over a list
that is already ranked: strategy, total, BUY/MAYBE/SKIP counts, best score,
average score, and creation time. It never sorts or filters.

```python
ranker = DefaultOpportunityRanker()
ordered = ranker.rank(opportunities, RankingStrategy.OPPORTUNITY_SCORE)
summary = RankingResult.from_ranked_opportunities(ordered)
```

Lot opportunity ranking is outside this flow and was not introduced by P1.10.
