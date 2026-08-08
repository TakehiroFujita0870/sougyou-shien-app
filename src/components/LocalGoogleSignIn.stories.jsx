import { createLocalGoogleAuthAdapter } from '../auth/localAuthAdapter';
import { LocalGoogleSignIn } from './LocalGoogleSignIn';

export default {
  title: 'Kadode/LocalGoogleSignIn',
  component: LocalGoogleSignIn,
};

export const SignedOut = {};

export const SignedIn = {
  loaders: [async () => {
    const authAdapter = createLocalGoogleAuthAdapter();
    await authAdapter.signIn();
    return { authAdapter };
  }],
  render: (_, { loaded }) => <LocalGoogleSignIn authAdapter={loaded.authAdapter} />,
};
