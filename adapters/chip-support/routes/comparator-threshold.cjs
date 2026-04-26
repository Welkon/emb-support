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
          notes: ['Declare bindings.comparator-threshold in the tool device/family profile first.']
        }
      );
    }

    if (binding.algorithm === 'unsupported') {
      return shared.buildUnsupported(context, 'comparator-threshold', options, identity, {
        notes: [binding.reason || 'This route explicitly declares no support for comparator-threshold.']
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
