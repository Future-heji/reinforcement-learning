import gym
import sys
import os
import itertools
import collections
import numpy as np
import tensorflow as tf
import time

from inspect import getsourcefile
current_path = os.path.dirname(os.path.abspath(getsourcefile(lambda:0)))
import_path = os.path.abspath(os.path.join(current_path, "../.."))

if import_path not in sys.path:
  sys.path.append(import_path)

# from lib import plotting
from lib.atari.state_processor import StateProcessor
from lib.atari import helpers as atari_helpers
from estimators import ValueEstimator, PolicyEstimator
from worker import make_copy_params_op


class PolicyEval(object):
    def __init__(self, env, policy_net, summary_writer):
        self.env = env
        self.global_policy_net = policy_net
        self.summary_writer = summary_writer
        self.sp = StateProcessor()

        self.video_dir = os.path.join(summary_writer.get_logdir(), "videos")
        os.makedirs(self.video_dir)

        with tf.variable_scope("policy_eval"):
            self.policy_net = PolicyEstimator(policy_net.num_outputs)

        # Op to copy params from global policy/valuenets
        self.copy_params_op = make_copy_params_op(
            tf.contrib.slim.get_variables(scope="global", collection=tf.GraphKeys.TRAINABLE_VARIABLES),
            tf.contrib.slim.get_variables(scope="policy_eval", collection=tf.GraphKeys.TRAINABLE_VARIABLES))

        self.env.monitor.start(directory=self.video_dir, video_callable=lambda x: True, resume=True)

    def _policy_net_predict(self, state, sess):
        feed_dict = { self.policy_net.states: [state] }
        preds = sess.run(self.policy_net.predictions, feed_dict)
        return preds["probs"][0]

    def eval_once(self, sess):
        with sess.as_default(), sess.graph.as_default():
          # Copy params to local model
          global_step, _ = sess.run([tf.contrib.framework.get_global_step(), self.copy_params_op])

          # Run an episode
          done = False
          state = atari_helpers.atari_make_initial_state(self.sp.process(self.env.reset()))
          total_reward = 0.0
          episode_length = 0
          while not done:
              action_probs = self._policy_net_predict(state, sess)
              action = np.random.choice(np.arange(len(action_probs)), p=action_probs)
              next_state, reward, done, _ = self.env.step(action)
              next_state = atari_helpers.atari_make_next_state(state, self.sp.process(next_state))
              total_reward += reward
              episode_length += 1
              state = next_state

          # Add summary
          episode_summary = tf.Summary()
          episode_summary.value.add(simple_value=total_reward, tag="total_reward")
          episode_summary.value.add(simple_value=episode_length, tag="episode_length")
          self.summary_writer.add_summary(episode_summary, global_step)
          self.summary_writer.flush()

          tf.logging.info("Eval results at step {}: total_reward {}, episode_length {}".format(global_step, total_reward, episode_length))

          return total_reward, episode_length

    def continuous_eval(self, eval_every, sess):
        while True:
            self.eval_once(sess)
            # Sleep until next evaluation cycle
            time.sleep(eval_every)