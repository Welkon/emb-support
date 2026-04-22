'use strict';

const shared = require('../core/shared.cjs');

module.exports = {
  runTool(context) {
    const options = shared.parseOptions(context);
    const identity = shared.resolveIdentity(options);
    const profiles = shared.resolveProfiles(identity);
    const binding = shared.resolveBinding('comparator-threshold', identity, profiles);

    if (!binding) {
      return shared.buildRouteRequired(
        context,
        'comparator-threshold',
        options,
        identity,
        profiles,
        {
          notes: ['请先在 tool device/family profile 中声明 bindings.comparator-threshold。']
        }
      );
    }

    if (binding.algorithm === 'unsupported') {
      return shared.buildUnsupported(context, 'comparator-threshold', options, identity, {
        notes: [binding.reason || '该 route 显式声明不支持 comparator-threshold。']
      });
    }

    const comparatorAlgorithm = shared.loadAlgorithm(binding.algorithm);
    const result = comparatorAlgorithm.run(options, binding, profiles);
    if (result.status !== 'ok') {
      return shared.buildUnsupported(context, 'comparator-threshold', options, identity, {
        notes: result.notes || []
      });
    }

    return shared.buildOk(
      context,
      'comparator-threshold',
      options,
      identity,
      result.outputs,
      result.notes
    );
  }
};
