from pydantic import BaseModel, ConfigDict, Field
class M(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', allow_inf_nan=False)
    x: float | None = Field(None, ge=0)
for value in [1, 1.5, '1', True, float('nan'), float('inf')]:
    try:
        print(repr(value), M(x=value))
    except Exception as exc:
        print(repr(value), 'ERR', str(exc).splitlines()[0])
