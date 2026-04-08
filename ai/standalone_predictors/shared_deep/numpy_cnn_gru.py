from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


REGIME_TO_INDEX = {"reset": 0, "neutral": 1, "continuation": 2}
INDEX_TO_REGIME = {value: key for key, value in REGIME_TO_INDEX.items()}


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - np.max(values, axis=1, keepdims=True)
    exp_values = np.exp(np.clip(shifted, -30.0, 30.0))
    denominator = np.sum(exp_values, axis=1, keepdims=True)
    return exp_values / np.clip(denominator, 1e-8, None)


@dataclass
class SequenceStandardScaler:
    mean: np.ndarray
    std: np.ndarray

    @classmethod
    def fit(cls, features: np.ndarray) -> "SequenceStandardScaler":
        flattened = np.asarray(features, dtype=np.float32).reshape(-1, features.shape[-1])
        mean = flattened.mean(axis=0)
        std = flattened.std(axis=0)
        std = np.where(std < 1e-6, 1.0, std)
        return cls(mean.astype(np.float32), std.astype(np.float32))

    def transform(self, features: np.ndarray) -> np.ndarray:
        payload = np.asarray(features, dtype=np.float32)
        return ((payload - self.mean.reshape(1, 1, -1)) / self.std.reshape(1, 1, -1)).astype(np.float32)

    def to_payload(self) -> dict[str, Any]:
        return {
            "format": "sequence_standard_scaler_v1",
            "mean": self.mean.astype(np.float32),
            "std": self.std.astype(np.float32),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "SequenceStandardScaler":
        return cls(
            mean=np.asarray(payload.get("mean"), dtype=np.float32),
            std=np.asarray(payload.get("std"), dtype=np.float32),
        )


class AdamOptimizer:
    def __init__(self, parameter_dict: dict[str, np.ndarray], learning_rate: float = 0.003, beta1: float = 0.9, beta2: float = 0.999, eps: float = 1e-8, weight_decay: float = 0.0) -> None:
        self.learning_rate = float(learning_rate)
        self.beta1 = float(beta1)
        self.beta2 = float(beta2)
        self.eps = float(eps)
        self.weight_decay = float(weight_decay)
        self.t = 0
        self.m = {name: np.zeros_like(value, dtype=np.float32) for name, value in parameter_dict.items()}
        self.v = {name: np.zeros_like(value, dtype=np.float32) for name, value in parameter_dict.items()}

    def step(self, parameter_dict: dict[str, np.ndarray], gradients: dict[str, np.ndarray]) -> None:
        self.t += 1
        for name, parameter in parameter_dict.items():
            gradient = np.asarray(gradients.get(name), dtype=np.float32)
            if gradient.size == 0:
                continue
            gradient = np.clip(gradient, -5.0, 5.0)
            if self.weight_decay and parameter.ndim > 1:
                gradient = gradient + self.weight_decay * parameter
            self.m[name] = self.beta1 * self.m[name] + (1.0 - self.beta1) * gradient
            self.v[name] = self.beta2 * self.v[name] + (1.0 - self.beta2) * (gradient * gradient)
            m_hat = self.m[name] / (1.0 - self.beta1 ** self.t)
            v_hat = self.v[name] / (1.0 - self.beta2 ** self.t)
            parameter -= (self.learning_rate * m_hat) / (np.sqrt(v_hat) + self.eps)


class NumpyCnnGruModel:
    def __init__(
        self,
        input_dim: int,
        main_dim: int,
        extra_dim: int = 0,
        regime_dim: int = 3,
        conv_channels: int = 16,
        hidden_size: int = 24,
        shared_size: int = 32,
        kernel_size: int = 3,
        seed: int = 20260403,
    ) -> None:
        self.input_dim = int(input_dim)
        self.main_dim = int(main_dim)
        self.extra_dim = int(extra_dim)
        self.regime_dim = int(regime_dim)
        self.conv_channels = int(conv_channels)
        self.hidden_size = int(hidden_size)
        self.shared_size = int(shared_size)
        self.kernel_size = max(1, int(kernel_size))
        rng = np.random.default_rng(int(seed))

        self.W_conv = (rng.normal(0.0, 0.08, size=(self.kernel_size * self.input_dim, self.conv_channels))).astype(np.float32)
        self.b_conv = np.zeros((self.conv_channels,), dtype=np.float32)

        self.W_z = (rng.normal(0.0, 0.08, size=(self.conv_channels, self.hidden_size))).astype(np.float32)
        self.U_z = (rng.normal(0.0, 0.08, size=(self.hidden_size, self.hidden_size))).astype(np.float32)
        self.b_z = np.zeros((self.hidden_size,), dtype=np.float32)
        self.W_r = (rng.normal(0.0, 0.08, size=(self.conv_channels, self.hidden_size))).astype(np.float32)
        self.U_r = (rng.normal(0.0, 0.08, size=(self.hidden_size, self.hidden_size))).astype(np.float32)
        self.b_r = np.zeros((self.hidden_size,), dtype=np.float32)
        self.W_h = (rng.normal(0.0, 0.08, size=(self.conv_channels, self.hidden_size))).astype(np.float32)
        self.U_h = (rng.normal(0.0, 0.08, size=(self.hidden_size, self.hidden_size))).astype(np.float32)
        self.b_h = np.zeros((self.hidden_size,), dtype=np.float32)

        self.W_shared = (rng.normal(0.0, 0.08, size=(self.hidden_size, self.shared_size))).astype(np.float32)
        self.b_shared = np.zeros((self.shared_size,), dtype=np.float32)
        self.W_main = (rng.normal(0.0, 0.08, size=(self.shared_size, self.main_dim))).astype(np.float32)
        self.b_main = np.zeros((self.main_dim,), dtype=np.float32)

        if self.extra_dim > 0:
            self.W_extra = (rng.normal(0.0, 0.08, size=(self.shared_size, self.extra_dim))).astype(np.float32)
            self.b_extra = np.zeros((self.extra_dim,), dtype=np.float32)
        else:
            self.W_extra = None
            self.b_extra = None

        if self.regime_dim > 0:
            self.W_regime = (rng.normal(0.0, 0.08, size=(self.shared_size, self.regime_dim))).astype(np.float32)
            self.b_regime = np.zeros((self.regime_dim,), dtype=np.float32)
        else:
            self.W_regime = None
            self.b_regime = None

    def parameter_dict(self) -> dict[str, np.ndarray]:
        payload = {
            "W_conv": self.W_conv,
            "b_conv": self.b_conv,
            "W_z": self.W_z,
            "U_z": self.U_z,
            "b_z": self.b_z,
            "W_r": self.W_r,
            "U_r": self.U_r,
            "b_r": self.b_r,
            "W_h": self.W_h,
            "U_h": self.U_h,
            "b_h": self.b_h,
            "W_shared": self.W_shared,
            "b_shared": self.b_shared,
            "W_main": self.W_main,
            "b_main": self.b_main,
        }
        if self.W_extra is not None and self.b_extra is not None:
            payload["W_extra"] = self.W_extra
            payload["b_extra"] = self.b_extra
        if self.W_regime is not None and self.b_regime is not None:
            payload["W_regime"] = self.W_regime
            payload["b_regime"] = self.b_regime
        return payload

    def architecture_payload(self) -> dict[str, Any]:
        return {
            "input_dim": self.input_dim,
            "main_dim": self.main_dim,
            "extra_dim": self.extra_dim,
            "regime_dim": self.regime_dim,
            "conv_channels": self.conv_channels,
            "hidden_size": self.hidden_size,
            "shared_size": self.shared_size,
            "kernel_size": self.kernel_size,
        }

    def load_state_dict(self, payload: dict[str, np.ndarray]) -> None:
        for name, value in payload.items():
            if hasattr(self, name):
                setattr(self, name, np.asarray(value, dtype=np.float32))

    def state_dict(self) -> dict[str, np.ndarray]:
        return {name: np.asarray(value, dtype=np.float32) for name, value in self.parameter_dict().items()}

    @classmethod
    def from_artifact_payload(cls, payload: dict[str, Any]) -> "NumpyCnnGruModel":
        architecture = dict(payload.get("architecture") or {})
        model = cls(**architecture)
        model.load_state_dict(dict(payload.get("weights") or {}))
        return model

    def _conv_windows(self, features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        batch_size, sequence_length, _feature_dim = features.shape
        pad = self.kernel_size // 2
        padded = np.pad(features, ((0, 0), (pad, pad), (0, 0)), mode="constant")
        windows = []
        for index in range(sequence_length):
            window = padded[:, index : index + self.kernel_size, :].reshape(batch_size, -1)
            windows.append(window)
        windows_flat = np.stack(windows, axis=1).astype(np.float32)
        conv_pre = windows_flat.reshape(batch_size * sequence_length, -1) @ self.W_conv + self.b_conv
        conv_pre = conv_pre.reshape(batch_size, sequence_length, self.conv_channels)
        conv_act = np.tanh(conv_pre).astype(np.float32)
        return windows_flat, conv_pre.astype(np.float32), conv_act

    def forward(self, features: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        inputs = np.asarray(features, dtype=np.float32)
        batch_size, sequence_length, _feature_dim = inputs.shape
        windows_flat, conv_pre, conv_act = self._conv_windows(inputs)

        gru_cache = []
        hidden = np.zeros((batch_size, self.hidden_size), dtype=np.float32)
        for index in range(sequence_length):
            x_t = conv_act[:, index, :]
            h_prev = hidden.copy()

            z_pre = x_t @ self.W_z + h_prev @ self.U_z + self.b_z
            r_pre = x_t @ self.W_r + h_prev @ self.U_r + self.b_r
            z = sigmoid(z_pre).astype(np.float32)
            r = sigmoid(r_pre).astype(np.float32)

            candidate_pre = x_t @ self.W_h + (r * h_prev) @ self.U_h + self.b_h
            h_tilde = np.tanh(candidate_pre).astype(np.float32)
            hidden = ((1.0 - z) * h_prev + z * h_tilde).astype(np.float32)
            gru_cache.append(
                {
                    "x": x_t,
                    "h_prev": h_prev,
                    "z": z,
                    "r": r,
                    "h_tilde": h_tilde,
                }
            )

        shared_pre = hidden @ self.W_shared + self.b_shared
        shared = np.maximum(shared_pre, 0.0).astype(np.float32)
        main_logits = shared @ self.W_main + self.b_main
        main_probs = sigmoid(main_logits).astype(np.float32)

        extra_logits = shared @ self.W_extra + self.b_extra if self.W_extra is not None and self.b_extra is not None else None
        extra_probs = softmax(extra_logits).astype(np.float32) if extra_logits is not None else None
        regime_logits = shared @ self.W_regime + self.b_regime if self.W_regime is not None and self.b_regime is not None else None
        regime_probs = softmax(regime_logits).astype(np.float32) if regime_logits is not None else None

        outputs = {
            "main_logits": main_logits.astype(np.float32),
            "main_probs": main_probs,
            "extra_logits": extra_logits.astype(np.float32) if extra_logits is not None else None,
            "extra_probs": extra_probs,
            "regime_logits": regime_logits.astype(np.float32) if regime_logits is not None else None,
            "regime_probs": regime_probs,
        }
        cache = {
            "windows_flat": windows_flat,
            "conv_pre": conv_pre,
            "conv_act": conv_act,
            "gru_cache": gru_cache,
            "hidden": hidden,
            "shared_pre": shared_pre.astype(np.float32),
            "shared": shared,
        }
        return outputs, cache

    def compute_loss(
        self,
        outputs: dict[str, np.ndarray],
        targets_main: np.ndarray,
        targets_extra: np.ndarray | None = None,
        targets_regime: np.ndarray | None = None,
        head_weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        weights = dict(head_weights or {})
        eps = 1e-7
        main_probs = np.clip(np.asarray(outputs["main_probs"], dtype=np.float32), eps, 1.0 - eps)
        targets_main = np.asarray(targets_main, dtype=np.float32)
        batch_size = max(1, targets_main.shape[0])

        main_loss = float(-np.mean(targets_main * np.log(main_probs) + (1.0 - targets_main) * np.log(1.0 - main_probs)))
        grad_main_logits = ((main_probs - targets_main) / max(1, targets_main.shape[0] * targets_main.shape[1])).astype(np.float32)
        total_loss = float(weights.get("main", 1.0)) * main_loss
        grad_main_logits *= float(weights.get("main", 1.0))

        grad_extra_logits = None
        extra_loss = None
        extra_accuracy = None
        if targets_extra is not None and outputs.get("extra_probs") is not None:
            extra_probs = np.clip(np.asarray(outputs["extra_probs"], dtype=np.float32), eps, 1.0)
            targets_extra = np.asarray(targets_extra, dtype=np.int64)
            extra_loss = float(-np.mean(np.log(extra_probs[np.arange(batch_size), targets_extra])))
            grad_extra_logits = extra_probs.copy()
            grad_extra_logits[np.arange(batch_size), targets_extra] -= 1.0
            grad_extra_logits = (grad_extra_logits / batch_size).astype(np.float32)
            grad_extra_logits *= float(weights.get("extra", 0.45))
            total_loss += float(weights.get("extra", 0.45)) * extra_loss
            extra_accuracy = float(np.mean(np.argmax(extra_probs, axis=1) == targets_extra))

        grad_regime_logits = None
        regime_loss = None
        regime_accuracy = None
        if targets_regime is not None and outputs.get("regime_probs") is not None:
            regime_probs = np.clip(np.asarray(outputs["regime_probs"], dtype=np.float32), eps, 1.0)
            targets_regime = np.asarray(targets_regime, dtype=np.int64)
            regime_loss = float(-np.mean(np.log(regime_probs[np.arange(batch_size), targets_regime])))
            grad_regime_logits = regime_probs.copy()
            grad_regime_logits[np.arange(batch_size), targets_regime] -= 1.0
            grad_regime_logits = (grad_regime_logits / batch_size).astype(np.float32)
            grad_regime_logits *= float(weights.get("regime", 0.20))
            total_loss += float(weights.get("regime", 0.20)) * regime_loss
            regime_accuracy = float(np.mean(np.argmax(regime_probs, axis=1) == targets_regime))

        return {
            "total_loss": total_loss,
            "main_loss": main_loss,
            "extra_loss": extra_loss,
            "regime_loss": regime_loss,
            "extra_accuracy": extra_accuracy,
            "regime_accuracy": regime_accuracy,
            "gradients": {
                "main_logits": grad_main_logits,
                "extra_logits": grad_extra_logits,
                "regime_logits": grad_regime_logits,
            },
        }

    def backward(self, cache: dict[str, Any], gradient_payload: dict[str, np.ndarray | None]) -> dict[str, np.ndarray]:
        shared = np.asarray(cache["shared"], dtype=np.float32)
        shared_pre = np.asarray(cache["shared_pre"], dtype=np.float32)
        hidden = np.asarray(cache["hidden"], dtype=np.float32)

        gradients = {name: np.zeros_like(parameter, dtype=np.float32) for name, parameter in self.parameter_dict().items()}
        d_shared = np.zeros_like(shared, dtype=np.float32)

        grad_main_logits = gradient_payload.get("main_logits")
        if grad_main_logits is not None:
            grad_main_logits = np.asarray(grad_main_logits, dtype=np.float32)
            gradients["W_main"] += shared.T @ grad_main_logits
            gradients["b_main"] += grad_main_logits.sum(axis=0)
            d_shared += grad_main_logits @ self.W_main.T

        grad_extra_logits = gradient_payload.get("extra_logits")
        if grad_extra_logits is not None and self.W_extra is not None and self.b_extra is not None:
            grad_extra_logits = np.asarray(grad_extra_logits, dtype=np.float32)
            gradients["W_extra"] += shared.T @ grad_extra_logits
            gradients["b_extra"] += grad_extra_logits.sum(axis=0)
            d_shared += grad_extra_logits @ self.W_extra.T

        grad_regime_logits = gradient_payload.get("regime_logits")
        if grad_regime_logits is not None and self.W_regime is not None and self.b_regime is not None:
            grad_regime_logits = np.asarray(grad_regime_logits, dtype=np.float32)
            gradients["W_regime"] += shared.T @ grad_regime_logits
            gradients["b_regime"] += grad_regime_logits.sum(axis=0)
            d_shared += grad_regime_logits @ self.W_regime.T

        d_shared_pre = d_shared * (shared_pre > 0.0).astype(np.float32)
        gradients["W_shared"] += hidden.T @ d_shared_pre
        gradients["b_shared"] += d_shared_pre.sum(axis=0)
        dh_next = d_shared_pre @ self.W_shared.T

        conv_act = np.asarray(cache["conv_act"], dtype=np.float32)
        d_conv_act = np.zeros_like(conv_act, dtype=np.float32)
        for time_index in reversed(range(conv_act.shape[1])):
            step_cache = cache["gru_cache"][time_index]
            x_t = np.asarray(step_cache["x"], dtype=np.float32)
            h_prev = np.asarray(step_cache["h_prev"], dtype=np.float32)
            z = np.asarray(step_cache["z"], dtype=np.float32)
            r = np.asarray(step_cache["r"], dtype=np.float32)
            h_tilde = np.asarray(step_cache["h_tilde"], dtype=np.float32)

            dh = dh_next
            dz = dh * (h_tilde - h_prev)
            dh_tilde = dh * z
            dh_prev = dh * (1.0 - z)

            da_h = dh_tilde * (1.0 - h_tilde * h_tilde)
            gradients["W_h"] += x_t.T @ da_h
            gradients["U_h"] += (r * h_prev).T @ da_h
            gradients["b_h"] += da_h.sum(axis=0)
            d_r_h_prev = da_h @ self.U_h.T
            dr = d_r_h_prev * h_prev
            dh_prev += d_r_h_prev * r

            da_r = dr * r * (1.0 - r)
            gradients["W_r"] += x_t.T @ da_r
            gradients["U_r"] += h_prev.T @ da_r
            gradients["b_r"] += da_r.sum(axis=0)
            dh_prev += da_r @ self.U_r.T

            da_z = dz * z * (1.0 - z)
            gradients["W_z"] += x_t.T @ da_z
            gradients["U_z"] += h_prev.T @ da_z
            gradients["b_z"] += da_z.sum(axis=0)
            dh_prev += da_z @ self.U_z.T

            dx = da_h @ self.W_h.T + da_r @ self.W_r.T + da_z @ self.W_z.T
            d_conv_act[:, time_index, :] = dx
            dh_next = dh_prev

        d_conv_pre = d_conv_act * (1.0 - conv_act * conv_act)
        d_conv_pre_flat = d_conv_pre.reshape(-1, self.conv_channels)
        windows_flat = np.asarray(cache["windows_flat"], dtype=np.float32).reshape(-1, self.kernel_size * self.input_dim)
        gradients["W_conv"] += windows_flat.T @ d_conv_pre_flat
        gradients["b_conv"] += d_conv_pre_flat.sum(axis=0)
        return gradients

    def predict_proba(self, features: np.ndarray) -> dict[str, np.ndarray]:
        outputs, _cache = self.forward(features)
        return outputs


def _topk_recall(probabilities: np.ndarray, targets: np.ndarray, top_k: int) -> float:
    if probabilities.size == 0:
        return 0.0
    top_indices = np.argsort(-probabilities, axis=1)[:, :top_k]
    recalls = []
    for row_index, indices in enumerate(top_indices):
        positives = set(np.where(targets[row_index] > 0.5)[0].tolist())
        if not positives:
            recalls.append(0.0)
            continue
        hits = sum(1 for index in indices if index in positives)
        recalls.append(hits / max(1, len(positives)))
    return float(np.mean(recalls)) if recalls else 0.0


def _exact_hit_mean(probabilities: np.ndarray, targets: np.ndarray, ticket_size: int) -> float:
    if probabilities.size == 0:
        return 0.0
    top_indices = np.argsort(-probabilities, axis=1)[:, :ticket_size]
    exact_hits = []
    for row_index, indices in enumerate(top_indices):
        positives = set(np.where(targets[row_index] > 0.5)[0].tolist())
        exact_hits.append(float(sum(1 for index in indices if index in positives)))
    return float(np.mean(exact_hits)) if exact_hits else 0.0


def evaluate_model(
    model: NumpyCnnGruModel,
    features: np.ndarray,
    targets_main: np.ndarray,
    targets_extra: np.ndarray | None = None,
    targets_regime: np.ndarray | None = None,
    head_weights: dict[str, float] | None = None,
    ticket_size: int = 6,
    top_k: int | None = None,
) -> dict[str, Any]:
    outputs = model.predict_proba(features)
    loss_payload = model.compute_loss(
        outputs=outputs,
        targets_main=targets_main,
        targets_extra=targets_extra,
        targets_regime=targets_regime,
        head_weights=head_weights,
    )
    main_probs = np.asarray(outputs["main_probs"], dtype=np.float32)
    top_k = max(ticket_size, int(top_k or (ticket_size * 2)))
    result = {
        "total_loss": float(loss_payload["total_loss"]),
        "main_loss": float(loss_payload["main_loss"]),
        "extra_loss": None if loss_payload["extra_loss"] is None else float(loss_payload["extra_loss"]),
        "regime_loss": None if loss_payload["regime_loss"] is None else float(loss_payload["regime_loss"]),
        "exact_hit_mean": _exact_hit_mean(main_probs, np.asarray(targets_main, dtype=np.float32), ticket_size=ticket_size),
        "topk_recall": _topk_recall(main_probs, np.asarray(targets_main, dtype=np.float32), top_k=top_k),
        "extra_accuracy": None if loss_payload["extra_accuracy"] is None else float(loss_payload["extra_accuracy"]),
        "regime_accuracy": None if loss_payload["regime_accuracy"] is None else float(loss_payload["regime_accuracy"]),
    }
    return result


def _split_batch(features: np.ndarray, batch_size: int) -> list[slice]:
    batch_slices = []
    total = int(features.shape[0])
    if total <= 0:
        return [slice(0, 0)]
    for start in range(0, total, max(1, batch_size)):
        batch_slices.append(slice(start, min(total, start + max(1, batch_size))))
    return batch_slices


def train_numpy_cnn_gru(
    features: np.ndarray,
    targets_main: np.ndarray,
    targets_extra: np.ndarray | None,
    targets_regime: np.ndarray | None,
    model_kwargs: dict[str, Any],
    training_config: dict[str, Any],
) -> dict[str, Any]:
    features = np.asarray(features, dtype=np.float32)
    targets_main = np.asarray(targets_main, dtype=np.float32)
    if features.shape[0] < 4:
        raise ValueError("Not enough sequence samples to train the deep model.")

    validation_ratio = float(training_config.get("validation_ratio", 0.18) or 0.18)
    validation_count = max(1, int(round(features.shape[0] * validation_ratio)))
    validation_count = min(validation_count, max(1, features.shape[0] - 1))
    split_index = max(1, features.shape[0] - validation_count)

    train_features_raw = features[:split_index]
    val_features_raw = features[split_index:]
    train_targets_main = targets_main[:split_index]
    val_targets_main = targets_main[split_index:]
    train_targets_extra = np.asarray(targets_extra[:split_index], dtype=np.int64) if targets_extra is not None else None
    val_targets_extra = np.asarray(targets_extra[split_index:], dtype=np.int64) if targets_extra is not None else None
    train_targets_regime = np.asarray(targets_regime[:split_index], dtype=np.int64) if targets_regime is not None else None
    val_targets_regime = np.asarray(targets_regime[split_index:], dtype=np.int64) if targets_regime is not None else None

    scaler = SequenceStandardScaler.fit(train_features_raw)
    train_features = scaler.transform(train_features_raw)
    val_features = scaler.transform(val_features_raw)

    model = NumpyCnnGruModel(
        input_dim=int(train_features.shape[-1]),
        main_dim=int(targets_main.shape[-1]),
        extra_dim=0 if targets_extra is None else int(np.max(targets_extra) + 1),
        regime_dim=0 if targets_regime is None else max(3, int(np.max(targets_regime) + 1)),
        conv_channels=int(training_config.get("conv_channels", 16) or 16),
        hidden_size=int(training_config.get("hidden_size", 24) or 24),
        shared_size=int(training_config.get("shared_size", 32) or 32),
        kernel_size=int(training_config.get("kernel_size", 3) or 3),
        seed=int(training_config.get("seed", 20260403) or 20260403),
    )
    optimizer = AdamOptimizer(
        model.parameter_dict(),
        learning_rate=float(training_config.get("learning_rate", 0.003) or 0.003),
        weight_decay=float(training_config.get("weight_decay", 0.0001) or 0.0001),
    )

    epochs = int(training_config.get("epochs", 24) or 24)
    batch_size = max(1, int(training_config.get("batch_size", 32) or 32))
    patience = max(1, int(training_config.get("early_stopping_patience", 5) or 5))
    min_delta = float(training_config.get("early_stopping_min_delta", 0.0005) or 0.0005)
    head_weights = dict(training_config.get("head_weights") or {})
    ticket_size = int(training_config.get("ticket_size", 6) or 6)
    top_k = int(training_config.get("top_k", ticket_size * 2) or (ticket_size * 2))

    best_loss = float("inf")
    best_epoch = 0
    best_state = None
    patience_left = patience
    history = []

    for epoch in range(1, epochs + 1):
        epoch_losses = []
        for batch_slice in _split_batch(train_features, batch_size):
            outputs, cache = model.forward(train_features[batch_slice])
            loss_payload = model.compute_loss(
                outputs=outputs,
                targets_main=train_targets_main[batch_slice],
                targets_extra=None if train_targets_extra is None else train_targets_extra[batch_slice],
                targets_regime=None if train_targets_regime is None else train_targets_regime[batch_slice],
                head_weights=head_weights,
            )
            gradients = model.backward(cache, loss_payload["gradients"])
            optimizer.step(model.parameter_dict(), gradients)
            epoch_losses.append(float(loss_payload["total_loss"]))

        train_eval = evaluate_model(
            model=model,
            features=train_features,
            targets_main=train_targets_main,
            targets_extra=train_targets_extra,
            targets_regime=train_targets_regime,
            head_weights=head_weights,
            ticket_size=ticket_size,
            top_k=top_k,
        )
        val_eval = evaluate_model(
            model=model,
            features=val_features,
            targets_main=val_targets_main,
            targets_extra=val_targets_extra,
            targets_regime=val_targets_regime,
            head_weights=head_weights,
            ticket_size=ticket_size,
            top_k=top_k,
        )
        history.append(
            {
                "epoch": epoch,
                "train_total_loss": float(np.mean(epoch_losses)) if epoch_losses else train_eval["total_loss"],
                "val_total_loss": val_eval["total_loss"],
                "train_exact_hit_mean": train_eval["exact_hit_mean"],
                "val_exact_hit_mean": val_eval["exact_hit_mean"],
                "val_topk_recall": val_eval["topk_recall"],
            }
        )

        if val_eval["total_loss"] + min_delta < best_loss:
            best_loss = float(val_eval["total_loss"])
            best_epoch = epoch
            best_state = model.state_dict()
            patience_left = patience
        else:
            patience_left -= 1
            if patience_left <= 0:
                break

    if best_state is not None:
        model.load_state_dict(best_state)

    final_train_eval = evaluate_model(
        model=model,
        features=train_features,
        targets_main=train_targets_main,
        targets_extra=train_targets_extra,
        targets_regime=train_targets_regime,
        head_weights=head_weights,
        ticket_size=ticket_size,
        top_k=top_k,
    )
    final_val_eval = evaluate_model(
        model=model,
        features=val_features,
        targets_main=val_targets_main,
        targets_extra=val_targets_extra,
        targets_regime=val_targets_regime,
        head_weights=head_weights,
        ticket_size=ticket_size,
        top_k=top_k,
    )

    return {
        "model": model,
        "scaler": scaler,
        "train_samples": int(train_features.shape[0]),
        "val_samples": int(val_features.shape[0]),
        "best_epoch": int(best_epoch),
        "history": history,
        "metrics": {
            "train": final_train_eval,
            "validation": final_val_eval,
        },
    }


def save_artifacts(
    model: NumpyCnnGruModel,
    scaler: SequenceStandardScaler,
    model_path: Path,
    scaler_path: Path,
) -> None:
    model_path.parent.mkdir(parents=True, exist_ok=True)
    scaler_path.parent.mkdir(parents=True, exist_ok=True)
    with model_path.open("wb") as handle:
        pickle.dump(
            {
                "format": "numpy_cnn_gru_v1",
                "architecture": model.architecture_payload(),
                "weights": model.state_dict(),
            },
            handle,
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    with scaler_path.open("wb") as handle:
        pickle.dump(scaler.to_payload(), handle, protocol=pickle.HIGHEST_PROTOCOL)


def load_artifacts(model_path: Path, scaler_path: Path) -> tuple[NumpyCnnGruModel, SequenceStandardScaler]:
    with model_path.open("rb") as handle:
        model_payload = pickle.load(handle)
    with scaler_path.open("rb") as handle:
        scaler_payload = pickle.load(handle)
    model = NumpyCnnGruModel.from_artifact_payload(dict(model_payload or {}))
    scaler = SequenceStandardScaler.from_payload(dict(scaler_payload or {}))
    return model, scaler
