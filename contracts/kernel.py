"""The Hawkes propagation kernel.

    lambda_j(t) = mu_j + sum_i sum_{t_k in H_i, t_k < t}
                  alpha_ij * beta_ij * exp(-beta_ij (t - t_k))

alpha_ij is the branching ratio contribution: expected failures at j caused by
one failure at i. Collect them into G; rho(G) < 1 is subcritical and cascades
die out, rho(G) >= 1 is supercritical and they explode.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Estimator = Literal["counting", "mle"]


class EdgeKernel(BaseModel):
    edge_id: str
    alpha: float = Field(ge=0.0, description="expected failures at dst per failure at src")
    beta: float = Field(gt=0.0, description="decay rate; 1/beta is mean propagation delay in seconds")
    n_obs: int = Field(ge=0, description="near-miss chains supporting this estimate")
    ci_low: float = Field(description="bootstrap CI on alpha")
    ci_high: float
    estimator: Estimator

    @property
    def mean_delay_s(self) -> float:
        return 1.0 / self.beta

    @property
    def is_thin(self) -> bool:
        """Few observations => the decision layer must widen its uncertainty.

        A confident recommendation built on three observations is exactly the
        failure mode that gets a safety system switched off after its first bad
        call.
        """
        return self.n_obs < 10


class Kernel(BaseModel):
    kernel_id: str
    city_id: str
    corpus_id: str
    fitted_at: datetime
    edges: dict[str, EdgeKernel] = Field(description="edge_id -> fitted kernel")
    mu: dict[str, float] = Field(description="node_id -> background intensity")
    spectral_radius: float = Field(
        description="rho(G) where G_ij = alpha_ij. >= 1 means globally supercritical."
    )

    @property
    def is_subcritical(self) -> bool:
        return self.spectral_radius < 1.0
