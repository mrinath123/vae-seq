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

"""Basic tests for all of the VAE implementations."""

import tensorflow as tf

from vae_seq import agent as agent_mod
from vae_seq import hparams as hparams_mod
from vae_seq import codec
from vae_seq import util
from vae_seq import vae as vae_mod


def _build_vae(hparams):
    """Constructs a VAE."""
    obs_encoder = codec.MLPObsEncoder(hparams)
    obs_decoder = codec.OneHotObsDecoder(hparams)
    agent = agent_mod.EncodeObsAgent(obs_encoder)
    return vae_mod.make(hparams, agent, obs_encoder, obs_decoder)


def _observed(hparams):
    """Test observations."""
    return tf.zeros([util.batch_size(hparams), util.sequence_size(hparams)] +
                    hparams.obs_shape, dtype=tf.int32)


def _inf_tensors(hparams, vae):
    """Simple inference graph."""
    observed = _observed(hparams)
    agent_inputs = agent_mod.null_inputs(
        util.batch_size(hparams), util.sequence_size(hparams))
    contexts = agent_mod.contexts_for_static_observations(
        observed, vae.agent, agent_inputs)
    latents, divs = vae.infer_latents(contexts, observed)
    log_probs = vae.log_prob_observed(contexts, latents, observed)
    elbo = tf.reduce_sum(log_probs - divs)
    return [observed, latents, divs, log_probs, elbo]


def _gen_tensors(hparams, gen_core):
    """Samples observations and latent variables from the VAE."""
    agent_inputs = agent_mod.null_inputs(
        util.batch_size(hparams), util.sequence_size(hparams))
    generated, sampled_latents, _ = gen_core.generate(agent_inputs)
    return [generated, sampled_latents]


def _test_assertions(inf_tensors, gen_tensors):
    """Returns in-graph assertions for testing."""
    observed, latents, divs, log_probs, elbo = inf_tensors
    generated, sampled_latents = gen_tensors
    assertions = [
        tf.assert_equal(
            tf.shape(observed), tf.shape(generated),
            message="Shapes: training data vs. generated data"),
        tf.assert_equal(
            tf.shape(latents), tf.shape(sampled_latents),
            message="Shapes: inferred latents vs. sampled latents"),
        tf.assert_equal(
            tf.shape(divs), tf.shape(log_probs),
            message="Shapes: divergences vs. log-probs"),
        tf.assert_equal(
            tf.shape(observed)[:2], tf.shape(latents)[:2],
            message="Batch & steps: observed vs latents"),
        tf.assert_equal(
            tf.shape(observed)[:2], tf.shape(divs)[:2],
            message="Batch & steps: observed vs divergences"),
        tf.assert_equal(
            tf.shape(observed)[:2], tf.shape(log_probs)[:2],
            message="Batch & steps: observed vs log_probs"),
        tf.assert_equal(
            tf.shape(generated)[:2], tf.shape(sampled_latents)[:2],
            message="Batch & steps: generated vs sampled latents"),
    ]
    vars_ = tf.trainable_variables()
    grads = tf.gradients(-elbo, vars_)
    for (var, grad) in zip(vars_, grads):
        assertions.append(tf.check_numerics(grad, "Gradient for " + var.name))
    return assertions


def _all_tensors(hparams, vae):
    """All tensors to evaluate in tests."""
    inf_tensors = _inf_tensors(hparams, vae)
    gen_tensors = _gen_tensors(hparams, vae.gen_core)
    assertions = _test_assertions(inf_tensors, gen_tensors)
    return inf_tensors, gen_tensors, assertions


class VAETest(tf.test.TestCase):

    def _test_vae(self, vae_type):
        """Make sure that all tensors and assertions evaluate without error."""
        hparams = hparams_mod.make_hparams(obs_shape=[2], vae_type=vae_type)
        vae = _build_vae(hparams)
        inf_tensors, gen_tensors, assertions = _all_tensors(hparams, vae)
        with self.test_session() as sess:
            sess.run(tf.global_variables_initializer())
            sess.run(inf_tensors + gen_tensors + assertions)

    def test_iseq(self):
        self._test_vae("ISEQ")

    def test_rnn(self):
        self._test_vae("RNN")

    def test_srnn(self):
        self._test_vae("SRNN")


if __name__ == "__main__":
    tf.test.main()
