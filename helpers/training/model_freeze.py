import logging
import os, re
from torch import nn

logger = logging.getLogger("ModelFreeze")
logger.setLevel(os.environ.get("SIMPLETUNER_LOG_LEVEL", "INFO"))


def freeze_transformer_blocks(
    model: nn.Module,
    target_blocks: str,
    first_unfrozen_dit_layer: int = 0,
    first_unfrozen_mmdit_layer: int = 0,
):
    for name, param in model.named_parameters():
        # Example names:
        #  single_transformer_blocks.31.ff.c_proj.weight
        #  joint_transformer_blocks.1.ff.c_proj.weight
        try:
            layer_group = name.split(".")[0]
            layer_number = int(name.split(".")[1])
            if target_blocks != "any":
                # We will exclude entire categories of blocks here if they aren't defined to be trained.
                if (
                    target_blocks == "dit"
                    and layer_group != "single_transformer_blocks"
                ):
                    continue
                if (
                    target_blocks == "mmdit"
                    and layer_group != "joint_transformer_blocks"
                ):
                    continue
            if (
                first_unfrozen_dit_layer is not None
                and first_unfrozen_dit_layer > 0
                and layer_group == "single_transformer_blocks"
                and layer_number < first_unfrozen_dit_layer
            ) or (
                first_unfrozen_mmdit_layer is not None
                and first_unfrozen_mmdit_layer > 0
                and layer_group == "joint_transformer_blocks"
                and layer_number < first_unfrozen_mmdit_layer
            ):
                param.requires_grad = False
                logger.debug(f"Freezing {name}.")
                continue
            else:
                logger.debug(f"Unfreezing {name}.")
                continue
        except Exception as e:
            logger.debug(f"Skipping {name} as it does not have a layer number.")
            if hasattr(param, "requires_grad"):
                param.requires_grad = False
            continue

    return model


def apply_bitfit_freezing(model, args):
    model_type = args.model_type
    if "lora" in model_type:
        # LoRAs don't have bias and arrive pre-frozen on the bottom.
        return model

    logger.debug("Applying BitFit freezing strategy for u-net tuning.")
    for name, param in model.named_parameters():
        if not hasattr(param, "requires_grad"):
            logger.debug(
                f"Skipping {name} as it does not have 'requires_grad' attribute."
            )
            continue
        # Freeze everything that's not a bias
        if "bias" not in name:
            param.requires_grad = False
        else:
            # Unfreeze biases
            param.requires_grad = True
    return model


def freeze_entire_component(component):
    for name, param in component.named_parameters():
        if hasattr(param, "requires_grad"):
            param.requires_grad = False
    return component


def freeze_text_encoder(args, component):
    from transformers import T5EncoderModel

    if (
        not args.train_text_encoder
        or not args.freeze_encoder
        or type(component) is T5EncoderModel
    ):
        if args.train_text_encoder:
            logger.info("Not freezing text encoder. Live dangerously and prosper!")
        return component
    method = args.freeze_encoder_strategy
    first_layer = args.freeze_encoder_before
    last_layer = args.freeze_encoder_after
    total_count = 0
    for name, param in component.named_parameters():
        total_count += 1
        pieces = name.split(".")
        if pieces[1] != "encoder" and pieces[2] != "layers":
            logger.info(f"Ignoring non-encoder layer: {name}")
            continue
        else:
            logger.debug(f"Freezing layer: {name}, which has keys: {pieces}")
        current_layer = int(pieces[3])

        freeze_param = False
        if method == "between":
            freeze_param = current_layer > first_layer or current_layer < last_layer
        elif method == "outside":
            freeze_param = first_layer <= current_layer <= last_layer
        elif method == "before":
            freeze_param = current_layer < first_layer
        elif method == "after":
            freeze_param = current_layer > last_layer
        else:
            raise ValueError(
                f"Invalid method {method}. Choose between 'between', 'outside', 'before' or 'after'."
            )

        if freeze_param:
            if hasattr(param, "requires_grad"):
                param.requires_grad = False
                # logger.debug(
                #     f"Froze layer {name} with method {method} and range {first_layer} - {last_layer}"
                # )
            else:
                # logger.info(
                #     f"Ignoring layer that does not mark as gradient capable: {name}"
                # )
                pass
    logger.info(
        f"Applied {method} method with range {first_layer} - {last_layer} to {total_count} total layers."
    )
    return component
