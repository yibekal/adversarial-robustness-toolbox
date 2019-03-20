from __future__ import absolute_import, division, print_function, unicode_literals

import logging

import numpy as np
from scipy.ndimage import rotate, shift

from art.attacks.attack import Attack

logger = logging.getLogger(__name__)


class SpatialTransformation(Attack):
    """
    Implementation of the spatial transformation attack using translation and rotation of inputs. The attack conducts
    black-box queries to the target model in a grid search over possible translations and rotations to find optimal
    attack parameters.
    Paper link: https://arxiv.org/abs/1712.02779
    """

    attack_params = Attack.attack_params + ['max_translation', 'num_translations', 'max_rotation', 'num_rotations']

    def __init__(self, classifier, max_translation=0.0, num_translations=1, max_rotation=0.0, num_rotations=1):
        """
        :param classifier: A trained model.
        :type classifier: :class:`.Classifier`
        :param max_translation: The maximum translation in any direction as percentage of image size.
        :type max_translation: `float`
        :param num_translations: The number of translations to search on grid spacing per direction.
        :type num_translations: `int`
        :param max_rotation: The maximum rotation in either direction in degrees.
        :type max_rotation: `float`
        :param num_rotations: The number of rotations to search on grid spacing.
        :type num_rotations: `int`
        """
        super(SpatialTransformation, self).__init__(classifier=classifier)
        kwargs = {'max_translation': max_translation,
                  'num_translations': num_translations,
                  'max_rotation': max_rotation,
                  'num_rotations': num_rotations
                  }
        self.set_params(**kwargs)

        self.fooling_rate = None
        self.attack_trans_x = None
        self.attack_trans_y = None
        self.attack_rot = None

    def generate(self, x, **kwargs):
        """
        Generate adversarial samples and return them in an array.

        :param x: An array with the original inputs.
        :type x: `np.ndarray`
        :param max_translation: The maximum translation in any direction as percentage of image size.
        :type max_translation: `float`
        :param num_translations: The number of translations to search on grid spacing per direction.
        :type num_translations: `int`
        :param max_rotation: The maximum rotation in either direction in degrees.
        :type max_rotation: `float`
        :param num_rotations: The number of rotations to search on grid spacing.
        :type num_rotations: `int`
        :param expectation: An expectation over transformations to be applied when computing
                            classifier gradients and predictions.
        :type expectation: :class:`.ExpectationOverTransformations`
        :return: An array holding the adversarial examples.
        :rtype: `np.ndarray`
        """
        logger.info('Computing spatial transformation based on grid search.')

        if self.attack_trans_x is None or self.attack_trans_y is None or self.attack_rot is None:
            self.set_params(**kwargs)

            y_pred = self.classifier.predict(x, logits=False)
            y_pred_max = np.argmax(y_pred, axis=1)

            nb_instances = len(x)
            self.min_ = np.min(x)
            self.max_ = np.max(x)

            # Determine grids
            max_num_pixel_trans_x = int(round((x.shape[1] * self.max_translation / 100.0)))
            max_num_pixel_trans_y = int(round((x.shape[2] * self.max_translation / 100.0)))

            grid_trans_x = [int(round(g)) for g in
                            list(np.linspace(-max_num_pixel_trans_x, max_num_pixel_trans_x, num=self.num_translations))]
            grid_trans_y = [int(round(g)) for g in
                            list(np.linspace(-max_num_pixel_trans_y, max_num_pixel_trans_y, num=self.num_translations))]
            grid_rot = list(np.linspace(-self.max_rotation, self.max_rotation, num=self.num_rotations))

            # Remove duplicates
            grid_trans_x = list(set(grid_trans_x))
            grid_trans_y = list(set(grid_trans_y))
            grid_rot = list(set(grid_rot))

            grid_trans_x.sort()
            grid_trans_y.sort()
            grid_rot.sort()

            # Search for worst case
            fooling_rate = 0.0
            x_adv = None
            trans_x = None
            trans_y = None
            rot = None

            for trans_x_i in grid_trans_x:
                for trans_y_i in grid_trans_y:
                    for rot_i in grid_rot:

                        # Generate the adversarial examples
                        x_adv_i = self._perturb(x, trans_x_i, trans_y_i, rot_i)

                        # Compute the error rate
                        y_adv_i = np.argmax(self.classifier.predict(x_adv_i, logits=False), axis=1)
                        fooling_rate_i = np.sum(y_pred_max != y_adv_i) / nb_instances

                        if fooling_rate_i > fooling_rate:
                            fooling_rate = fooling_rate_i
                            trans_x = trans_x_i
                            trans_y = trans_y_i
                            rot = rot_i
                            x_adv = np.copy(x_adv_i)

            self.fooling_rate = fooling_rate
            self.attack_trans_x = trans_x
            self.attack_trans_y = trans_y
            self.attack_rot = rot

            logger.info('Success rate of spatial transformation attack: %.2f%%', self.fooling_rate)
            logger.info('Attack-translation in x: %.2f%%', self.attack_trans_x)
            logger.info('Attack-translation in y: %.2f%%', self.attack_trans_y)
            logger.info('Attack-rotation: %.2f%%', self.attack_rot)

        else:
            x_adv = self._perturb(x, self.attack_trans_x, self.attack_trans_y, self.attack_rot)

        return x_adv

    def _perturb(self, x, trans_x, trans_y, rot):
        if self.classifier.channel_index == 3:
            x_adv = shift(x, [0, trans_x, trans_y, 0])
            x_adv = rotate(x_adv, angle=rot, axes=(1, 2), reshape=False)
        elif self.classifier.channel_index == 1:
            x_adv = shift(x, [0, 0, trans_x, trans_y])
            x_adv = rotate(x_adv, angle=rot, axes=(2, 3), reshape=False)
        else:
            raise ValueError("Unsupported channel index.")

        x_adv = np.clip(x_adv, self.min_, self.max_)
        return x_adv

    def set_params(self, **kwargs):
        """
        Take in a dictionary of parameters and applies attack-specific checks before saving them as attributes.

        :param max_translation: The maximum translation in any direction as percentage of image size.
        :type max_translation: `float`
        :param num_translations: The number of translations to search on grid spacing per direction.
        :type num_translations: `int`
        :param max_rotation: The maximum rotation in degrees.
        :type max_rotation: `float`
        :param num_rotations: The number of rotations to search on grid spacing.
        :type num_rotations: `int`
        """
        super(SpatialTransformation, self).set_params(**kwargs)

        for key, value in kwargs.items():
            if key in self.attack_params:
                setattr(self, key, value)

        if not isinstance(self.max_translation, (float, int)) or self.max_translation < 0 or self.max_translation > 100:
            raise ValueError("The maximum translation must be in the range [0, 100].")

        if not isinstance(self.num_translations, int) or self.num_translations <= 0:
            raise ValueError("The number of translations must be a positive integer.")

        if not isinstance(self.max_rotation, (float, int)) or self.max_rotation < 0 or self.max_translation > 180:
            raise ValueError("The maximum rotation must be in the range [0, 180].")

        if not isinstance(self.num_rotations, int) or self.num_rotations <= 0:
            raise ValueError("The number of rotations must be a positive integer.")

        return True
