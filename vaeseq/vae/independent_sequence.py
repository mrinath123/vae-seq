"""Simple extension of VAE to a sequential setting.

Notation:
 - z_1:T are hidden states, random variables.
 - d_1:T, e_1:T, and f_1:T are deterministic RNN outputs.
 - x_1:T are the observed states.
 - c_1:T are per-timestep contexts.

        Generative model               Inference model
      =====================         =====================
      x_1               x_t             z_1        z_t
       ^                 ^               ^          ^
       |                 |               |          |
      d_1 ------------> d_t             f_1 <----- f_t
       ^                 ^               ^          ^
       |                 |               |          |
   [c_1, z_1]        [c_t, z_t]         e_1 -----> e_t
                                         ^          ^
                                         |          |
                                     [c_1, x_1] [c_t, x_t]
"""

import sonnet as snt
import tensorflow as tf

from . import base
from .. import dist_module
from .. import latent as latent_mod
from .. import util

class IndependentSequence(base.VAEBase):
    """Implementation of a Sequential VAE with independent latent variables."""

    def __init__(self, hparams, agent, obs_encoder, obs_decoder, name=None):
        self._hparams = hparams
        self._obs_encoder = obs_encoder
        self._obs_decoder = obs_decoder
        super(IndependentSequence, self).__init__(agent, name=name)

    def _init_submodules(self):
        hparams = self._hparams
        self._d_core = util.make_rnn(hparams, name="d_core")
        self._e_core = util.make_rnn(hparams, name="e_core")
        self._f_core = util.make_rnn(hparams, name="f_core")
        self._q_z = latent_mod.LatentDecoder(hparams, name="latent_q")
        self._latent_prior_distcore = LatentPrior(hparams)
        self._observed_distcore = ObsDist(self._d_core, self._obs_decoder)

    def infer_latents(self, contexts, observed):
        hparams = self._hparams
        batch_size = util.batch_size_from_nested_tensors(observed)
        enc_observed = snt.BatchApply(self._obs_encoder, n_dims=2)(observed)
        e_outs, _ = tf.nn.dynamic_rnn(
            self._e_core,
            util.concat_features((contexts, enc_observed)),
            initial_state=self._e_core.initial_state(batch_size))
        f_outs, _ = util.reverse_dynamic_rnn(
            self._f_core,
            e_outs,
            initial_state=self._f_core.initial_state(batch_size))
        q_zs = self._q_z.dist(
            snt.BatchApply(self._q_z, n_dims=2)(f_outs),
            name="q_zs")
        latents = q_zs.sample()
        p_zs = tf.contrib.distributions.MultivariateNormalDiag(
            loc=tf.zeros_like(latents),
            scale_diag=tf.ones_like(latents),
            name="p_zs")
        divs = util.calc_kl(hparams, latents, q_zs, p_zs)
        return latents, divs


class ObsDist(dist_module.DistCore):
    """DistCore for producing p(observation | context, latent)."""

    def __init__(self, d_core, obs_decoder, name=None):
        super(ObsDist, self).__init__(name=name)
        self._d_core = d_core
        self._obs_decoder = obs_decoder

    @property
    def state_size(self):
        return self._d_core.state_size

    @property
    def event_size(self):
        return self._obs_decoder.event_size

    @property
    def event_dtype(self):
        return self._obs_decoder.event_dtype

    def dist(self, params, name=None):
        return self._obs_decoder.dist(params, name=name)

    def _next_state(self, d_state, event=None):
        del event  # Not used.
        return d_state

    def _build(self, inputs, d_state):
        context, latent = inputs
        d_out, d_state = self._d_core(util.concat_features(context), d_state)
        return self._obs_decoder((d_out, latent)), d_state


class LatentPrior(dist_module.DistCore):
    """DistCore that samples standard normal latents."""

    def __init__(self, hparams, name=None):
        super(LatentPrior, self).__init__(name=name)
        self._hparams = hparams

    @property
    def state_size(self):
        return ()

    @property
    def event_size(self):
        return tf.TensorShape(self._hparams.latent_size)

    @property
    def event_dtype(self):
        return tf.float32

    def dist(self, batch_size, name=None):
        dims = tf.stack([batch_size, self._hparams.latent_size])
        loc = tf.zeros(dims)
        loc.set_shape([None, self._hparams.latent_size])
        scale_diag = tf.ones(dims)
        scale_diag.set_shape([None, self._hparams.latent_size])
        return tf.contrib.distributions.MultivariateNormalDiag(
            loc=loc, scale_diag=scale_diag,
            name=name or self.module_name + "_dist")

    def _next_state(self, state_arg, event=None):
        del state_arg, event  # No state.
        return ()

    def _build(self, context, state):
        del state  # No state needed.
        batch_size = util.batch_size_from_nested_tensors(context)
        return batch_size, ()
