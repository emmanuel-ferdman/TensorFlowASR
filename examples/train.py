# Copyright 2023 Huy Le Nguyen (@nglehuy)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from tensorflow_asr import tf  # import to aid logging messages
from tensorflow_asr.configs.config import Config
from tensorflow_asr.datasets import asr_dataset
from tensorflow_asr.featurizers import text_featurizers
from tensorflow_asr.utils import cli_util, env_util, file_util


def main(
    config_path: str,
    dataset_type: str,
    bs: int = None,
    spx: int = 1,
    devices: list = None,
    mxp: str = "none",
    jit_compile: bool = False,
    ga_steps: int = None,
):
    tf.keras.backend.clear_session()
    env_util.setup_seed()
    strategy = env_util.setup_strategy(devices)
    env_util.setup_mxp(mxp=mxp)

    config = Config(config_path)

    text_featurizer = text_featurizers.get(config)

    train_dataset = asr_dataset.get(
        text_featurizer=text_featurizer,
        dataset_config=config.data_config.train_dataset_config,
        dataset_type=dataset_type,
    )
    eval_dataset = asr_dataset.get(
        text_featurizer=text_featurizer,
        dataset_config=config.data_config.eval_dataset_config,
        dataset_type=dataset_type,
    )

    shapes = asr_dataset.get_global_shape(config, strategy, train_dataset, eval_dataset, batch_size=bs)

    train_data_loader = train_dataset.create(shapes["batch_size"])
    eval_data_loader = eval_dataset.create(shapes["batch_size"])

    with strategy.scope():
        model = tf.keras.models.model_from_config(config.model_config)
        model.make(**shapes)
        if config.learning_config.pretrained:
            model.load_weights(
                config.learning_config.pretrained,
                by_name=file_util.is_hdf5_filepath(config.learning_config.pretrained),
                skip_mismatch=True,
            )
        model.compile(
            optimizer=tf.keras.optimizers.get(config.learning_config.optimizer_config),
            steps_per_execution=spx,
            blank=text_featurizer.blank,
            jit_compile=jit_compile,
            mxp=mxp,
            ga_steps=ga_steps or config.learning_config.running_config.ga_steps,
            apply_gwn_config=config.learning_config.apply_gwn_config,
        )
        model.summary()

    callbacks = [
        tf.keras.callbacks.TerminateOnNaN(),
        tf.keras.callbacks.ModelCheckpoint(**config.learning_config.running_config.checkpoint),
        tf.keras.callbacks.BackupAndRestore(**config.learning_config.running_config.backup_and_restore),
        tf.keras.callbacks.TensorBoard(**config.learning_config.running_config.tensorboard),
    ]
    if config.learning_config.running_config.early_stopping:
        callbacks.append(tf.keras.callbacks.EarlyStopping(**config.learning_config.running_config.early_stopping))

    model.fit(
        train_data_loader,
        epochs=config.learning_config.running_config.num_epochs,
        validation_data=eval_data_loader,
        callbacks=callbacks,
        steps_per_epoch=train_dataset.total_steps,
        validation_steps=eval_dataset.total_steps if eval_data_loader else None,
    )


if __name__ == "__main__":
    cli_util.run(main)
