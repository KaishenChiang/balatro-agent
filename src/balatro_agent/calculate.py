"""Bounded explicit arithmetic; no game client, file reader, eval or strategy."""
import math
import statistics

from .local_audit import LocalAudit

ERRORS = {'invalid_input': '操作或显式数字输入不符合计算契约。',
          'division_by_zero': '除数为零，未定义商。',
          'resource_limit': '计算输入或结果超过资源限制。',
          'internal_error': '计算未通过内部检查。'}
OPERATIONS = ('sum', 'difference', 'product', 'quotient', 'mean', 'median',
              'variance_population', 'combination', 'hypergeometric')


class CalculateError(Exception):
    pass


def calculate_explicit(operation, inputs):
    if operation not in OPERATIONS or not isinstance(inputs, dict):
        raise CalculateError('invalid_input')
    assumptions = ['仅使用调用者显式提供且已合法获得的公开数字；不读取游戏状态。']
    if operation in OPERATIONS[:7]:
        values = inputs.get('values')
        if set(inputs) != {'values'} or not isinstance(values, list) or not 1 <= len(values) <= 200:
            raise CalculateError('invalid_input')
        if any(type(n) not in (int, float) or not math.isfinite(n) or abs(n) > 1e12 for n in values):
            raise CalculateError('invalid_input')
        if operation in ('difference', 'quotient') and len(values) != 2:
            raise CalculateError('invalid_input')
        if operation == 'quotient' and values[1] == 0:
            raise CalculateError('division_by_zero')
        if operation == 'sum':
            result, formula = math.fsum(values), 'Σ values'
        elif operation == 'difference':
            result, formula = values[0] - values[1], 'values[0] - values[1]'
        elif operation == 'product':
            result, formula = math.prod(values), 'Π values'
        elif operation == 'quotient':
            result, formula = values[0] / values[1], 'values[0] / values[1]'
        elif operation == 'mean':
            result, formula = statistics.mean(values), 'Σ values / len(values)'
        elif operation == 'median':
            result, formula = statistics.median(values), 'ordered middle value (mean of two middle values for even count)'
        else:
            result, formula = statistics.pvariance(values), 'Σ (value - mean)^2 / len(values)'
    elif operation == 'combination':
        if set(inputs) != {'n', 'k'} or any(type(inputs.get(k)) is not int for k in ('n', 'k')):
            raise CalculateError('invalid_input')
        n, k = inputs['n'], inputs['k']
        if not 0 <= k <= n <= 1000:
            raise CalculateError('invalid_input')
        result, formula = math.comb(n, k), 'n! / (k! (n-k)!)'
    else:
        keys = {'population', 'successes', 'draws', 'min_successes', 'max_successes'}
        if set(inputs) != keys or any(type(inputs.get(k)) is not int for k in keys):
            raise CalculateError('invalid_input')
        n, k, d, lo, hi = (inputs[key] for key in ('population', 'successes', 'draws', 'min_successes', 'max_successes'))
        if not (0 <= k <= n <= 1000 and 0 <= d <= n and 0 <= lo <= hi <= d):
            raise CalculateError('invalid_input')
        numerator = sum(math.comb(k, x) * math.comb(n-k, d-x) for x in range(max(lo, d-(n-k)), min(hi, k)+1))
        result = numerator / math.comb(n, d)
        formula = 'Σ[x=lo..hi] C(successes,x) C(population-successes,draws-x) / C(population,draws)'
        assumptions += ['固定已知总体；不放回、均匀随机抽样；指定范围外概率不计入。',
                        '菜单牌组总组成未必等于当前可抽池；可抽池前提未知时此结果仅为条件概率。']
    if abs(result) > 1e100 or (isinstance(result, float) and not math.isfinite(result)):
        raise CalculateError('resource_limit')
    return {'status': 'ok', 'schema_version': 'calculate-1', 'read_only': True,
            'operation': operation, 'inputs': inputs, 'formula': formula, 'result': result, 'assumptions': assumptions}


class Calculator:
    def __init__(self, settings):
        self.audit = LocalAudit(settings)

    def calculate(self, operation, inputs):
        try:
            result = calculate_explicit(operation, inputs)
        except CalculateError as exc:
            result = {'status': str(exc), 'reason': ERRORS[str(exc)], 'read_only': True, 'schema_version': 'calculate-1'}
        except (ValueError, TypeError, OverflowError):
            result = {'status': 'invalid_input', 'reason': ERRORS['invalid_input'], 'read_only': True, 'schema_version': 'calculate-1'}
        return self.audit.deliver('calculate', result)
