# -*- coding: utf-8 -*-

from game import Game
import random
from chainer import Chain, Variable, optimizers
import chainer.functions as F
import chainer.links     as L
import numpy             as np
from collections import deque
import chainer.serializers as S
import os.path

class QNetwork(Chain):
    def __init__(self):
        super(QNetwork, self).__init__(
            conv1=F.Convolution2D(3, 16, ksize=3, pad=1),
            conv2=F.Convolution2D(16, 32, ksize=3, pad=1, stride=2),
            conv3=F.Convolution2D(32, 64, ksize=3, pad=1, stride=2),
            l1=F.Linear(768, 512),
            l2=F.Linear(512, 3))

    def __call__(self, state):
        h1 = F.leaky_relu(self.conv1(state))
        h2 = F.leaky_relu(self.conv2(h1))
        h3 = F.leaky_relu(self.conv3(h2))
        h4 = F.leaky_relu(self.l1(h3))
        h5 = self.l2(h4)
        return h5

class AiController():
    OBSERVE_FRAME = 3200
    REPLAY_MEMORY = 50000
    BATCH = 32
    GAMMA = 0.97

    def __init__(self, game, player, policy, with_train, verbose):
        self.__with_train = with_train
        self.__verbose = verbose
        self.__policy = policy
        self.__game = game
        self.__player = player
        self.__network = QNetwork()
        self.__network.to_gpu()
        self.__optimizer = optimizers.Adam()
        self.__optimizer.setup(self.__network)
        self.__history = deque()
        self.__timestamp = 0
        self.__point = 0.0
        self.load()

    def log(self, str):
        if self.__verbose:
            print(str)

    def save(self):
        S.save_hdf5('network.model', self.__network)

    def load(self):
        if os.path.isfile('network.model'):
            S.load_hdf5('network.model', self.__network)

    def get_display_as_state(self):
        state = []
        for line in self.__game.current_display():
            state_line = []
            state.append(state_line)
            for point in line:
                value = [0.0, 0.0, 0.0]
                if point != None:
                    value[point.state_index()] = 1.0
                state_line.append(value)
        return state

    def current_state(self):
        state = np.asarray(self.get_display_as_state())
        state = state.astype(np.float32)
        state = state.reshape(1, 3, Game.DISPLAY_HEIGHT, Game.DISPLAY_WIDTH)
        return state

    def next(self):
        if len(self.__history) > 0:
            prev_frame = self.__history[-1]
        if len(self.__history) > AiController.REPLAY_MEMORY:
            self.__history.popleft()

        state = self.current_state()
        q_value = self.__network(state)

        if self.__policy == 'greedy':
            action = np.argmax(q_value.data.reshape(-1))
            self.log("GREEDY: {}".format(action))
        elif self.__policy == 'egreedy':
            if random.random() < 0.1:
                action = random.randint(0, 2)
                self.log("ε-greedy RANDOM: {}".format(action))
            else:
                action = np.argmax(q_value.data.reshape(-1))
                self.log("ε-greedy GREEDY: {}".format(action))
        elif self.__policy == 'softmax':
            q_value_soft = F.softmax(q_value / 0.1)
            prob = q_value_soft.data.reshape(-1)
            action = np.random.choice(len(prob), p=prob)
            self.log("Q: {}, SOFTMAX: {}".format(q_value.data, q_value_soft.data))

        if action == 0:
            self.__player.move_left()
        elif action == 1:
            self.__player.move_right()
        elif action == 2:
            self.__player.shoot_bullet()

        prev_point = self.__game.total_point()

        ###################################################################################
        self.__game.update()
        self.__timestamp += 1
        ###################################################################################

        curr_point = self.__game.total_point() - prev_point
        self.__point = self.__point * AiController.GAMMA + (curr_point / 100.0)

        self.log("TIME: {}, GAME SCORE: {}".format(self.__timestamp, self.__point))

        reward = (curr_point) / 100.0
        state_prime = self.current_state()

        self.__history.append({
            "state": state,
            "action": action,
            "reward": reward,
            "state_prime": state_prime
        })

        if self.__timestamp > AiController.OBSERVE_FRAME:
            minibatch = random.sample(self.__history, AiController.BATCH)

            inputs = np.zeros((AiController.BATCH, 3, Game.DISPLAY_HEIGHT, Game.DISPLAY_WIDTH))
            targets = np.zeros((inputs.shape[0], 3))

            for i in range(0, len(minibatch)):
                data = minibatch[i]
                state = data['state']
                action = data['action']
                reward = data['reward']
                state_prime = data['state_prime']

                inputs[i : i + 1] = state
                targets[i] = self.__network(state).data
                Q_sa = self.__network(state_prime)

                targets[i, action] = reward + AiController.GAMMA * np.max(Q_sa.data)

            x = self.__network(inputs.astype(np.float32))
            loss = F.mean_squared_error(x, targets.astype(np.float32))
            self.__optimizer.update(lambda: loss)

            print("LOSS: {}".format(loss.data))

            if self.__timestamp % 100 == 0:
                self.log('save model!')
                self.save()

