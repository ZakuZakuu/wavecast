class MixRendererUnavailableError(RuntimeError):
    """The configured ffmpeg binary is not available."""


class MixSourceUnavailableError(RuntimeError):
    """A canonical clip does not resolve to an existing owned audio source."""


class MixRenderError(RuntimeError):
    """ffmpeg could not render a valid output artifact."""
