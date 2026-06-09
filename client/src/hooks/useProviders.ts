import { useQuery } from '@tanstack/react-query';
import apiClient from '../services/api';
import type { ProviderInfo } from '../types';

const fetchProviders = async (includeModels: boolean): Promise<ProviderInfo[]> => {
  const response = await apiClient.get('/providers', {
    params: { include_models: includeModels },
  });
  // The backend endpoint returns the data directly, not nested in a `data` property.
  return response.data;
};

export const useProviders = (includeModels = true) => {
  return useQuery({
    queryKey: ['providers', { includeModels }],
    queryFn: () => fetchProviders(includeModels),
  });
};
