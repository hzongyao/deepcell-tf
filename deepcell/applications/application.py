# Copyright 2016-2019 The Van Valen Lab at the California Institute of
# Technology (Caltech), with support from the Paul Allen Family Foundation,
# Google, & National Institutes of Health (NIH) under Grant U24CA224309-01.
# All rights reserved.
#
# Licensed under a modified Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.github.com/vanvalenlab/deepcell-tf/LICENSE
#
# The Work provided may be used for non-commercial academic purposes only.
# For any other use of the Work, including commercial use, please contact:
# vanvalenlab@gmail.com
#
# Neither the name of Caltech nor the names of its contributors may be used
# to endorse or promote products derived from this software without specific
# prior written permission.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Base class for applications"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np

from deepcell_toolbox.utils import resize, tile_image, untile_image


class Application(object):
    """Application object that takes a model with weights and manages predictions

        Args:
            model (tf.model): Tensorflow model with weights loaded
            model_image_shape (tuple, optional): Shape of input expected by model.
                Defaults to `(128, 128, 1)`.
            dataset_metadata (optional): Any input, e.g. str or dict. Defaults to None.
            model_metadata (optional): Any input, e.g. str or dict. Defaults to None.
            model_mpp (float, optional): Microns per pixel resolution of training data.
                Defaults to 0.65.
            preprocessing_fn (function, optional): Preprocessing function to apply to data
                prior to prediction. Defaults to None.
            postprocessing_fn (function, optional): Postprocessing function to apply
                to data after prediction. Defaults to None.
                Must accept an input of a list of arrays and then return a single array.

        Raises:
            ValueError: `Preprocessing_fn` must be a callable function
            ValueError: `Postprocessing_fn` must be a callable function
        """

    def __init__(self,
                 model,
                 model_image_shape=(128, 128, 1),
                 model_mpp=0.65,
                 preprocessing_fn=None,
                 postprocessing_fn=None,
                 dataset_metadata=None,
                 model_metadata=None):

        self.model = model

        self.model_image_shape = model_image_shape
        # Require dimension 1 larger than model_input_shape due to addition of batch dimension
        self.required_rank = len(self.model_image_shape) + 1

        self.required_channels = self.model_image_shape[-1]

        self.model_mpp = model_mpp
        self.preprocessing_fn = preprocessing_fn
        self.postprocessing_fn = postprocessing_fn
        self.dataset_metadata = dataset_metadata
        self.model_metadata = model_metadata

        # Test that pre and post processing functions are callable
        if self.preprocessing_fn is not None and not callable(self.preprocessing_fn):
            raise ValueError('Preprocessing_fn must be a callable function.')
        if self.postprocessing_fn is not None and not callable(self.postprocessing_fn):
            raise ValueError('Postprocessing_fn must be a callable function.')

    def predict(self, x):
        raise NotImplementedError

    def _resize_input(self, image, image_mpp):
        """Checks if there is a difference between image and model resolution
        and resizes if they are different. Otherwise returns the unmodified image.

        Args:
            image (array): Input image to resize
            image_mpp (float): Microns per pixel for the input image

        Returns:
            array: Input image resized if necessary to match `model_mpp`
        """

        # Don't scale the image if mpp is the same or not defined
        if image_mpp not in {None, self.model_mpp}:
            scale_factor = image_mpp / self.model_mpp
            new_shape = (int(image.shape[1] * scale_factor),
                         int(image.shape[2] * scale_factor))
            image = resize(image, new_shape, data_format='channels_last')

        return image

    def _preprocess(self, image, **kwargs):
        """Preprocess image if `preprocessing_fn` is defined.
        Otherwise return unmodified image
        """

        if self.preprocessing_fn is not None:
            image = self.preprocessing_fn(image, **kwargs)

        return image

    def _tile_input(self, image):
        """Tile the input image to match shape expected by model
        using the deepcell_toolbox function.
        Currently only supports 4d images and otherwise raises an error

        Args:
            image (array): Input image to tile

        Raises:
            ValueError: Input images must have only 4 dimensions

        Returns:
            (array, dict): Tuple of tiled image and dictionary of tiling specs
        """

        if len(image.shape) != 4:
            raise ValueError('deepcell_toolbox.tile_image only supports 4d images.'
                             'Image submitted for predict has {} dimensions'.format(
                                 len(image.shape)))

        # Check difference between input and model image size
        x_diff = image.shape[1] - self.model_image_shape[0]
        y_diff = image.shape[2] - self.model_image_shape[1]

        # Check if the input is smaller than model image size
        if x_diff < 0 or y_diff < 0:
            # Calculate padding
            x_diff, y_diff = abs(x_diff), abs(y_diff)
            x_pad = (x_diff // 2, x_diff // 2 + 1) if x_diff % 2 else (x_diff // 2, x_diff // 2)
            y_pad = (y_diff // 2, y_diff // 2 + 1) if y_diff % 2 else (y_diff // 2, y_diff // 2)

            tiles = np.pad(image, [(0, 0), x_pad, y_pad, (0, 0)], 'reflect')
            tiles_info = {'padding': True,
                          'x_pad': x_pad,
                          'y_pad': y_pad}
        # Otherwise tile images larger than model size
        else:
            # Tile images, needs 4d
            tiles, tiles_info = tile_image(image, model_input_shape=self.model_image_shape)

        return tiles, tiles_info

    def _postprocess(self, image, **kwargs):
        """Applies postprocessing function to image if one has been defined.
        Otherwise returns unmodified image.

        Args:
            image (array or list): Input to postprocessing function
                either an array or list of arrays

        Returns:
            array: labeled image
        """

        if self.postprocessing_fn is not None:
            image = self.postprocessing_fn(image, **kwargs)

            # Restore channel dimension if not already there
            if len(image.shape) == self.required_rank - 1:
                image = np.expand_dims(image, axis=-1)

        elif isinstance(image, list) and len(image) == 1:
            image = image[0]

        return image

    def _untile_output(self, output_tiles, tiles_info):
        """Untiles either a single array or a list of arrays
        according to a dictionary of tiling specs

        Args:
            output_tiles (array or list): Array or list of arrays
            tiles_info (dict): Dictionary of tiling specs output by tiling function

        Returns:
            array or list: Array or list according to input with untiled images
        """

        # If padding was used, remove padding
        if tiles_info.get('padding', False):
            def _process(im, tiles_info):
                x_pad, y_pad = tiles_info['x_pad'], tiles_info['y_pad']
                out = im[:, x_pad[0]:-x_pad[1], y_pad[0]:-y_pad[1], :]
                return out
        # Otherwise untile
        else:
            def _process(im, tiles_info):
                out = untile_image(im, tiles_info, model_input_shape=self.model_image_shape)
                return out

        if isinstance(output_tiles, list):
            output_images = [_process(o, tiles_info) for o in output_tiles]
        else:
            output_images = _process(output_tiles, tiles_info)

        return output_images

    def _resize_output(self, image, original_shape):
        """Rescales input if the shape does not match the original shape
        excluding the batch and channel dimensions

        Args:
            image (array): Image to be rescaled to original shape
            original_shape (tuple): Shape of the original input image

        Returns:
            array: Rescaled image
        """

        # Compare x,y based on rank of image
        if len(image.shape) == 4:
            same = image.shape[1:-1] == original_shape[1:-1]
        elif len(image.shape) == 3:
            same = image.shape[1:] == original_shape[1:-1]
        else:
            same = image.shape == original_shape[1:-1]

        # Resize if same is false
        if not same:
            # Resize function only takes the x,y dimensions for shape
            new_shape = original_shape[1:-1]
            image = resize(image, new_shape,
                           data_format='channels_last',
                           labeled_image=True)
        return image

    def _run_model(self,
                   image,
                   batch_size=4,
                   preprocess_kwargs={}):
        """Run the model to generate output probabilities on the data.

        Args:
            image (np.array): Input image with shape `[batch, x, y, channel]`
            batch_size (int, optional): Number of images to predict on per batch. Defaults to 4.
            preprocess_kwargs (dict, optional): Kwargs to pass to preprocessing function.
                Defaults to {}.

        Returns:
            np.array: Model outputs
        """

        # Preprocess image if function is defined
        image = self._preprocess(image, **preprocess_kwargs)

        # Tile images, raises error if the image is not 4d
        tiles, tiles_info = self._tile_input(image)

        # Run images through model
        output_tiles = self.model.predict(tiles, batch_size=batch_size)

        # Untile images
        output_images = self._untile_output(output_tiles, tiles_info)

        return output_images

    def _predict_segmentation(self,
                              image,
                              batch_size=4,
                              image_mpp=None,
                              preprocess_kwargs={},
                              postprocess_kwargs={}):
        """Generates a labeled image of the input running prediction with
        appropriate pre and post processing functions.

        Input images are required to have 4 dimensions `[batch, x, y, channel]`. Additional
        empty dimensions can be added using `np.expand_dims`

        Args:
            image (np.array): Input image with shape `[batch, x, y, channel]`
            batch_size (int, optional): Number of images to predict on per batch. Defaults to 4.
            image_mpp (float, optional): Microns per pixel for the input image. Defaults to None.
            preprocess_kwargs (dict, optional): Kwargs to pass to preprocessing function.
                Defaults to {}.
            postprocess_kwargs (dict, optional): Kwargs to pass to postprocessing function.
                Defaults to {}.

        Raises:
            ValueError: Input data must match required rank of the application, calculated as
                one dimension more (batch dimension) than expected by the model

            ValueError: Input data must match required number of channels of application

        Returns:
            np.array: Labeled image
        """

        # Check input size of image
        if len(image.shape) != self.required_rank:
            raise ValueError('Input data must have {} dimensions. '
                             'Input data only has {} dimensions'.format(
                                 self.required_rank, len(image.shape)))

        if image.shape[-1] != self.required_channels:
            raise ValueError('Input data must have {} channels. '
                             'Input data only has {} channels'.format(
                                 self.required_channels, image.shape[-1]))

        # Resize image, returns unmodified if appropriate
        resized_image = self._resize_input(image, image_mpp)

        # Generate model outputs
        output_images = self._run_model(image=resized_image, batch_size=batch_size,
                                        preprocess_kwargs=preprocess_kwargs)

        # Postprocess predictions to create label image
        label_image = self._postprocess(output_images, **postprocess_kwargs)

        # Resize label_image back to original resolution if necessary
        label_image = self._resize_output(label_image, image.shape)

        return label_image
