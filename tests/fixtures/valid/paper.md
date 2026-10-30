# Affinity-Model: Improving AS Routing Models via AS Affinity Behavior Inference

## I. Introduction

Understanding the routing behavior exhibited by ASes is crucial. Prior research often
models AS routing behaviors with oversimplified AS relationships.

## II. Background and Related Works

The Gao-Rexford model abstracts routing policies into p2c and p2p relationships.

## IV. Detailed Design of Affinity-Model

### B. Establishment of d2a links

We use PathRadar to infer the RIB-in paths of each source AS, then compare observed
paths against the inferred candidate paths to identify delegator-anchor (d2a) links.

### C. Extensive inference of d2a links

We train an XGBoost classifier on features of pre d2a links extracted from full VPs.

## V. Evaluation

### B. Datasets

We use routing snapshots from Route Views and RIPE RIS in January 2022.

### C. Evaluation on IRR Records

*Table VI: Different categories of AS link policies*

AM achieves 81% precision and 79% recall on d2a links.

### D. Evaluation on AS Paths

*Fig. 6: AS path coverage ratio for different models*

AM models 85.9% of AS routing behaviors in the actual Internet.

## VI. Conclusion

Affinity behaviors explain a large portion of AS routing decisions.
