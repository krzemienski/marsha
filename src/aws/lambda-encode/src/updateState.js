// DUPLICATE CODE: src/aws/lambda-update-state/src/updateState
/**
 * Post an update to the state of an object to any endpoint, using hmac with a shared secret
 * to sign the object key and provide authorization for the request.
 */
const request = require('request-promise-native');
const crypto = require('crypto');

const { ENDPOINT, SHARED_SECRET } = process.env;
const DISABLE_SSL_VALIDATION = JSON.parse(process.env.DISABLE_SSL_VALIDATION);

module.exports = async (key, state) => {
  const hmac = crypto.createHmac('sha256', SHARED_SECRET);
  hmac.update(key);
  const signature = hmac.digest('hex');

  const body = {
    key,
    signature,
    state,
  };

  console.log(`Updating state: POST ${ENDPOINT} \n ${JSON.stringify(body)}`);

  await request({
    body,
    json: true,
    method: 'POST',
    strictSSL: DISABLE_SSL_VALIDATION ? false : true,
    uri: ENDPOINT,
  });

  console.log(`Updated ${key}. New state is (${state}).`);
};
