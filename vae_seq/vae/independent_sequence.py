# Copyright 2017 Google, Inc.,
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

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
from tensorflow.contrib import distributions

from . import base
from . import latent as latent_mod
from .. import dist_module
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
        self._observed_distcore = ObsDist(
            hparams, self._d_core, self._obs_decoder)

    def infer_latents(self, contexts, observed):
        hparams = self._hparams
        batch_size = util.batch_size(hparams)
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
        p_zs = distributions.MultivariateNormalDiag(
            loc=tf.zeros_like(latents),
            scale_diag=tf.ones_like(latents),
            name="p_zs")
        divs = util.calc_kl(hparams, latents, q_zs, p_zs)
        return latents, divs


class ObsDist(dist_module.DistCore):
    """DistCore for producing p(observation | context, latent)."""

    def __init__(self, hparams, d_core, obs_decoder, name=None):
        super(ObsDist, self).__init__(name=name)
        self._hparams = hparams
        self._d_core = d_core
        self._obs_decoder = obs_decoder

    @property
    def state_size(self):
        return self._d_core.state_size

    @property
    def event_size(self):
        return tf.TensorShape(self._hparams.obs_shape)

    @property
    def event_dtype(self):
        return self._obs_decoder.event_dtype

    def dist(self, params):
        return self._obs_decoder.dist(params)

    def _next_state(self, d_state, event=None):
        return d_state

    def _build(self, inputs, d_state):
        context, latent = inputs
        d_out, d_state = self._d_core(util.concat_features(context), d_state)
        return self._obs_decoder(d_out, latent), d_state


class LatentPrior(dist_module.DistCore):
    """DistCore that samples standard normal latents."""

    def __init__(self, hparams, name=None):
        super(LatentPrior, self).__init__(name=name)
        self._hparams = hparams
        with self._enter_variable_scope():
            dims = tf.stack([util.batch_size(hparams), hparams.latent_size])
            loc = tf.zeros(dims)
            loc.set_shape([None, hparams.latent_size])
            scale_diag = tf.ones(dims)
            scale_diag.set_shape([None, hparams.latent_size])
            self._dist = distributions.MultivariateNormalDiag(
                loc=loc, scale_diag=scale_diag, name="prior_z")

    @property
    def state_size(self):
        return ()

    @property
    def event_size(self):
        return tf.TensorShape(self._hparams.latent_size)

    @property
    def event_dtype(self):
        return self._dist.dtype

    def dist(self, params):
        del params  # The latent distribution is constant.
        return self._dist

    def _next_state(self, state_arg, event=None):
        del state_arg, event  # No state.
        return ()

    def _build(self, context, state):
        del context, state  # No state or context needed.
        return (), ()
